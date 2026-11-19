from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from astrbot.api import AstrBotConfig, logger, sp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from export import export_user  # noqa: E402
from store import (  # noqa: E402
    StoreError,
    UserContextStore,
    build_user_prompt,
    normalize_qq,
    qq_user_hash,
)

PLUGIN_NAME = "astrbot_plugin_fatfish_user_context"
DEFAULT_DATA_DIR = "/home/ubuntu/AstrBot/data/fatfish_user_context"
DEFAULT_EXPORT_DIR = "/home/ubuntu/exports/fatfish_user_context"
DEFAULT_PERSONA_ID = "宇文尚元的蓝色大肥鱼"
REQUEST_INJECTED_ATTR = "_fatfish_user_context_injected"
KB_STATE_KEY = "fatfish_user_context_kb_state"


@register(
    PLUGIN_NAME,
    "FatFish",
    "按 QQ 用户加载独立介绍、长期记忆和知识库配置",
    "0.1.0",
)
class FatFishUserContext(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = str(config.get("data_dir") or DEFAULT_DATA_DIR)
        self.export_dir = str(config.get("export_dir") or DEFAULT_EXPORT_DIR)
        self.store = UserContextStore(data_dir)
        self._core_sync_lock = asyncio.Lock()
        self._kb_lock = asyncio.Lock()

    def _enabled(self) -> bool:
        return bool(self.config.get("enable", True))

    @staticmethod
    def _is_qq_private(event: AstrMessageEvent) -> bool:
        if event.get_group_id():
            return False
        platform_name = str(event.get_platform_name() or "").lower()
        platform_id = str(event.get_platform_id() or "").lower()
        return platform_name in {"aiocqhttp", "napcat", "qq"} or platform_id in {
            "aiocqhttp",
            "napcat",
            "napcat-qq",
            "qq",
        }

    def _event_qq(self, event: AstrMessageEvent) -> str | None:
        if not self._enabled() or not self._is_qq_private(event):
            return None
        try:
            return normalize_qq(str(event.get_sender_id() or ""))
        except ValueError:
            return None

    def _command_allowed(self, event: AstrMessageEvent) -> bool:
        return self._event_qq(event) is not None and event.is_admin()

    def _top_k(self) -> int:
        try:
            return max(1, int(self.config.get("top_k", 5)))
        except (TypeError, ValueError):
            return 5

    def _max_chars(self, key: str, default: int) -> int:
        try:
            return max(0, int(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    async def _apply_kb(self, event: AstrMessageEvent) -> None:
        async with self._kb_lock:
            await self._apply_kb_locked(event)

    async def _apply_kb_locked(self, event: AstrMessageEvent) -> None:
        qq = self._event_qq(event)
        if qq is None:
            return
        umo = event.unified_msg_origin
        try:
            binding = self.store.get_binding(qq)
        except StoreError as exc:
            logger.error(f"[user_context] 绑定配置无效，已关闭个性化知识库：{exc}")
            binding = {"enabled": False, "kb_ids": []}
        if binding is None:
            state = await sp.session_get(umo, KB_STATE_KEY, default={})
            if isinstance(state, dict) and state.get("managed"):
                previous = state.get("previous")
                if state.get("had_previous") and isinstance(previous, dict):
                    await sp.session_put(umo, "kb_config", previous)
                else:
                    await sp.session_remove(umo, "kb_config")
                await sp.session_remove(umo, KB_STATE_KEY)
                logger.info(
                    "[user_context] 用户已解绑，恢复原知识库配置：user=%s",
                    qq_user_hash(qq)[:12],
                )
            return

        kb_ids: list[str] = []
        if binding["enabled"]:
            try:
                # Validate both optional documents before enabling personal KB access.
                self.store.load_user_documents(qq)
                kb_ids = list(binding["kb_ids"])
            except StoreError as exc:
                logger.error(f"[user_context] 用户文件校验失败，已关闭个性化知识库：{exc}")

        desired = {"kb_ids": kb_ids, "top_k": self._top_k()}
        current = await sp.session_get(umo, "kb_config", default=None)
        state = await sp.session_get(umo, KB_STATE_KEY, default={})
        if not (isinstance(state, dict) and state.get("managed")):
            previous = current if isinstance(current, dict) else None
            await sp.session_put(
                umo,
                KB_STATE_KEY,
                {
                    "managed": True,
                    "had_previous": previous is not None,
                    "previous": previous,
                },
            )
        if isinstance(current, dict):
            if current.get("kb_ids") == desired["kb_ids"] and current.get(
                "top_k", 5
            ) == desired["top_k"]:
                return
        await sp.session_put(umo, "kb_config", desired)
        logger.info(
            "[user_context] 已更新会话知识库配置：user=%s, kb_count=%d",
            qq_user_hash(qq)[:12],
            len(kb_ids),
        )

    async def _sync_core(self) -> str:
        if not self._enabled():
            return "插件已停用，未同步主人格"
        persona_id = str(self.config.get("persona_id") or "").strip()
        if not persona_id:
            return "未配置 persona_id，未同步主人格"
        core = self.store.read_core()
        if not core.strip():
            raise StoreError("core.md 为空，拒绝覆盖主人格")

        async with self._core_sync_lock:
            manager = self.context.persona_manager
            existing = await manager.get_persona(persona_id)
            if existing is None:
                raise StoreError(f"AstrBot 主人格不存在：{persona_id}")
            old_prompt = existing.system_prompt or ""
            if old_prompt == core:
                return f"主人格已是最新：{persona_id}"
            backup = self.store.write_persona_backup(persona_id, old_prompt)
            await manager.update_persona(persona_id, system_prompt=core)
            logger.info(
                "[user_context] 主人格已从 core.md 同步：persona=%s, backup=%s",
                persona_id,
                backup,
            )
            return f"主人格已同步：{persona_id}\n旧版本备份：{backup}"

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        if not self._enabled():
            return
        try:
            result = await self._sync_core()
            logger.info("[user_context] %s", result)
        except Exception as exc:
            logger.error(f"[user_context] 主人格同步失败，保留原人格：{exc}", exc_info=True)

    @filter.on_waiting_llm_request()
    async def prepare_llm_request(self, event: AstrMessageEvent) -> None:
        try:
            await self._apply_kb(event)
        except Exception as exc:
            event.stop_event()
            logger.error(
                f"[user_context] 会话知识库配置失败，已停止本次请求：{exc}",
                exc_info=True,
            )

    @filter.on_llm_request()
    async def inject_user_context(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        try:
            await self._apply_kb(event)
        except Exception as exc:
            event.stop_event()
            logger.error(
                f"[user_context] 请求前知识库配置失败，已停止本次请求：{exc}",
                exc_info=True,
            )
            return

        if getattr(req, REQUEST_INJECTED_ATTR, False):
            return
        setattr(req, REQUEST_INJECTED_ATTR, True)
        qq = self._event_qq(event)
        if qq is None:
            return
        try:
            binding = self.store.get_binding(qq)
        except StoreError as exc:
            logger.error(f"[user_context] 绑定配置无效，已拒绝注入用户资料：{exc}")
            return
        if binding is None or not binding["enabled"]:
            return
        try:
            documents = self.store.load_user_documents(qq)
        except StoreError as exc:
            logger.error(f"[user_context] 已拒绝注入用户资料：{exc}")
            return
        overlay = build_user_prompt(
            documents["intro"],
            documents["memory"],
            max_intro_chars=self._max_chars("max_intro_chars", 4000),
            max_memory_chars=self._max_chars("max_memory_chars", 6000),
        )
        if overlay:
            req.system_prompt = f"{req.system_prompt or ''}{overlay}"

    @filter.command("qq知识库列表")
    async def list_knowledge_bases(
        self,
        event: AstrMessageEvent,
        page: str = "1",
    ):
        if not self._command_allowed(event):
            return
        try:
            page_number = max(1, int(page))
        except ValueError:
            yield event.plain_result("页码必须是正整数")
            return
        kbs = sorted(
            await self.context.kb_manager.list_kbs(),
            key=lambda item: (item.kb_name, item.kb_id),
        )
        if not kbs:
            yield event.plain_result("当前没有已加载的知识库")
            return
        page_size = 20
        page_count = (len(kbs) + page_size - 1) // page_size
        page_number = min(page_number, page_count)
        start = (page_number - 1) * page_size
        lines = [f"知识库列表：第 {page_number}/{page_count} 页，共 {len(kbs)} 个"]
        for kb in kbs[start : start + page_size]:
            lines.append(
                f"{kb.kb_id} | {kb.kb_name} | 文档 {kb.doc_count} | 块 {kb.chunk_count}"
            )
        if page_count > 1:
            lines.append("翻页：/qq知识库列表 <页码>")
        yield event.plain_result("\n".join(lines))

    @filter.command("qq知识库")
    async def manage_knowledge_bases(
        self,
        event: AstrMessageEvent,
        qq: str = "",
        operation: str = "",
        kb_id: str = "",
    ):
        if not self._command_allowed(event):
            return
        try:
            target_qq = normalize_qq(qq)
        except ValueError:
            yield event.plain_result(
                "用法：/qq知识库 <QQ号> [+|- <知识库id>]"
            )
            return

        if not operation and not kb_id:
            try:
                binding = self.store.get_binding(target_qq)
            except StoreError as exc:
                yield event.plain_result(f"绑定配置无效：{exc}")
                return
            user_hash = qq_user_hash(target_qq)
            if binding is None:
                yield event.plain_result(
                    f"QQ：{target_qq}\n用户哈希：{user_hash}\n"
                    "状态：未绑定，使用 AstrBot 默认知识库配置"
                )
                return
            lines = [
                f"QQ：{target_qq}",
                f"用户哈希：{user_hash}",
                f"状态：{'已启用' if binding['enabled'] else '已停用'}",
            ]
            if not binding["kb_ids"]:
                lines.append("知识库：无（明确不使用）")
            else:
                lines.append("知识库：")
                for item in binding["kb_ids"]:
                    helper = await self.context.kb_manager.get_kb(item)
                    name = helper.kb.kb_name if helper else "不存在或未加载"
                    lines.append(f"+ {item} | {name}")
            yield event.plain_result("\n".join(lines))
            return

        if operation not in {"+", "-"} or not kb_id.strip():
            yield event.plain_result(
                "用法：/qq知识库 <QQ号> [+|- <知识库id>]"
            )
            return
        kb_id = kb_id.strip()
        helper = await self.context.kb_manager.get_kb(kb_id)
        if operation == "+" and helper is None:
            yield event.plain_result(f"知识库不存在或未加载：{kb_id}")
            return

        try:
            if operation == "+":
                changed = self.store.add_kb(target_qq, kb_id)
                action = "已添加" if changed else "已存在，无需添加"
            else:
                changed = self.store.remove_kb(target_qq, kb_id)
                action = "已删除引用" if changed else "未绑定或未引用，未修改"
        except (StoreError, ValueError, OSError) as exc:
            yield event.plain_result(f"配置写入失败：{exc}")
            return

        if target_qq == str(event.get_sender_id() or ""):
            try:
                await self._apply_kb(event)
            except Exception as exc:
                logger.error(f"[user_context] 指令后会话刷新失败：{exc}", exc_info=True)
        binding = self.store.get_binding(target_qq)
        count = len(binding["kb_ids"]) if binding else 0
        yield event.plain_result(
            f"{action}：{kb_id}\n该 QQ 当前引用 {count} 个知识库，"
            "下一条私聊消息起生效。"
        )

    @filter.command("qq人格重载")
    async def reload_core_persona(self, event: AstrMessageEvent):
        if not self._command_allowed(event):
            return
        try:
            result = await self._sync_core()
        except Exception as exc:
            yield event.plain_result(f"主人格同步失败，原人格未替换：{exc}")
            return
        yield event.plain_result(result)

    @filter.command("qq记忆导出")
    async def export_memory(self, event: AstrMessageEvent, qq: str = ""):
        if not self._command_allowed(event):
            return
        try:
            target_qq = normalize_qq(qq)
            target = await asyncio.to_thread(
                export_user,
                self.store,
                target_qq,
                self.export_dir,
            )
        except (StoreError, ValueError, OSError) as exc:
            yield event.plain_result(f"导出失败：{exc}")
            return
        yield event.plain_result(f"导出完成：{target}")

    async def terminate(self):
        logger.info("[user_context] 插件已卸载")
