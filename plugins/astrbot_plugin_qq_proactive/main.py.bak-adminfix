# -*- coding: utf-8 -*-
"""主动伴聊 QQ：按人设在活跃时段内主动给主人 QQ 私聊发消息。

设计原则：
- 宁可不发，不可骚扰：每日硬上限 + 最小间隔 + 静默时段三重限制。
- LLM 有否决权：模型判断此刻不适合说话时输出 PASS，本轮跳过。
- 零手工配 UMO：主人在目标私聊里发 `/proactive 绑定` 即可自动写入配置。
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

try:  # 优先用 AstrBot 官方数据目录，取不到时退回相对路径
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    DATA_DIR = os.path.join(get_astrbot_data_path(), "plugin_data", "astrbot_plugin_qq_proactive")
except Exception:  # pragma: no cover - 兜底路径
    DATA_DIR = os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_qq_proactive")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

RECENT_CAP = 20  # 喂给 LLM 的最近上下文条数上限（双方合计）


def _parse_hhmm(text: str, default_minutes: int) -> int:
    """把 "HH:MM" 解析为当日分钟数，非法输入返回默认值。"""
    try:
        hh, mm = (text or "").strip().split(":")
        minutes = int(hh) * 60 + int(mm)
        if 0 <= minutes <= 24 * 60:
            return minutes
    except Exception:
        pass
    return default_minutes


@register(
    "astrbot_plugin_qq_proactive",
    "dsh-whale",
    "按人设主动给主人 QQ 私聊发消息：活跃时段、每日上限、冷却、静默一应俱全",
    "1.0.0",
)
class ProactiveCompanion(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config if config is not None else context.get_config()
        self._task = None
        self._state = {
            "sent_date": "",      # 本地日期 YYYY-MM-DD，用于每日计数重置
            "sent_today": 0,      # 今日已发条数
            "last_send_ts": 0.0,  # 上次发送的 epoch 秒
            "recent": [],         # [{role: bot|user, text, ts}]
        }
        self._load_state()

    # ───────────────────────────── 生命周期 ─────────────────────────────

    async def initialize(self):
        """AstrBot 激活插件后启动后台随机间隔循环。"""
        os.makedirs(DATA_DIR, exist_ok=True)
        if not self.config.get("ENABLE", True):
            logger.info("[主动伴聊] 总开关已关闭，后台任务不启动")
            return
        if not self._target_umo():
            logger.info("[主动伴聊] 尚未绑定目标会话，请在目标 QQ 私聊中发送：/proactive 绑定")
        if not (self.config.get("API_KEY") or "").strip():
            logger.warning("[主动伴聊] 未配置 API_KEY，暂时无法生成主动消息")
        self._task = asyncio.create_task(self._loop())

    async def terminate(self):
        """插件重载/停服时取消后台任务并落盘状态。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self._save_state()

    async def _loop(self):
        """随机间隔睡眠 -> 尝试发送。间隔均匀分布在 MIN~MAX 之间。"""
        while True:
            lo = max(5, int(self.config.get("MIN_INTERVAL_MINUTES", 90) or 90))
            hi = max(lo, int(self.config.get("MAX_INTERVAL_MINUTES", 240) or 240))
            await asyncio.sleep(random.uniform(lo, hi) * 60)
            try:
                await self._maybe_send(force=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[主动伴聊] 本轮发送流程异常（跳过本轮）: {exc}")

    # ───────────────────────────── 核心逻辑 ─────────────────────────────

    def _target_umo(self) -> str:
        return (self.config.get("TARGET_UMO") or self._state.get("target_umo") or "").strip()

    def _in_active_window(self, now: datetime) -> bool:
        """判断当前时刻是否处于活跃时段，支持跨午夜（如 21:00~06:00）。"""
        start = _parse_hhmm(self.config.get("ACTIVE_START", "09:00"), 9 * 60)
        end = _parse_hhmm(self.config.get("ACTIVE_END", "23:00"), 23 * 60)
        cur = now.hour * 60 + now.minute
        if start <= end:
            return start <= cur < end
        return cur >= start or cur < end

    def _roll_daily_count(self, now: datetime):
        """按本地日期滚动重置每日计数。"""
        today = now.strftime("%Y-%m-%d")
        if self._state.get("sent_date") != today:
            self._state["sent_date"] = today
            self._state["sent_today"] = 0

    def _recent_block(self) -> str:
        if not self._state.get("recent"):
            return "（最近没有可参考的对话记录）"
        lines = []
        for item in self._state["recent"][-RECENT_CAP:]:
            who = "对方（主人）" if item.get("role") == "user" else "你"
            lines.append(f"- {who}: {item.get('text', '')}")
        return "\n".join(lines)

    async def _generate_message(self, force: bool) -> str | None:
        """调用 LLM 生成一条主动消息；模型输出 PASS 或空表示本轮沉默。

        Args:
            force: 测试模式，要求模型必须产出消息内容。

        Returns:
            消息文本；None 表示不适合发送。
        """
        api_key = (self.config.get("API_KEY") or "").strip()
        if not api_key:
            logger.warning("[主动伴聊] 未配置 API_KEY，跳过生成")
            return None
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.warning("[主动伴聊] 当前环境缺少 openai 包，无法生成")
            return None

        now = datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        persona = (self.config.get("PERSONA") or "").strip() or "你是一个住在 QQ 里的贴心小伙伴，性格开朗调皮。"
        owner = (self.config.get("OWNER_NAME") or "主人").strip()
        sys_prompt = (
            f"{persona}\n\n"
            f"你对对方的称呼：{owner}。\n"
            "你要决定要不要主动找对方说话。规则：\n"
            "1. 现在的时间是 {time}（周{wd}）。结合人设、时间和最近对话判断此刻开口是否自然。\n"
            "2. 不适合开口（太晚、刚聊过、没话找话）时，只输出一行：PASS\n"
            "3. 适合开口时，只输出要发送的消息正文，不要任何前缀、引号、表情堆砌。\n"
            "4. 消息要短（10~60字），像真人朋友随口发来的一条，不要模板化的“在吗/记得吃饭”式群发腔。\n"
            "5. 不要重复最近对话里已经说过的话题。"
        ).replace("{time}", now.strftime("%H:%M")).replace("{wd}", weekday)
        user_prompt = (
            f"最近上下文：\n{self._recent_block()}\n\n"
            + ("现在请立即生成一条要发给对方的消息（测试模式，不允许 PASS）。" if force
               else "现在是本轮主动时机，请按规则输出 PASS 或消息正文。")
        )

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=(self.config.get("API_BASE") or "https://api.openai.com/v1").strip(),
            timeout=60,
        )
        resp = await client.chat.completions.create(
            model=(self.config.get("MODEL") or "gpt-4o-mini").strip(),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=1.0,
            max_tokens=200,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text or text.upper().startswith("PASS"):
            return None
        # 保险：模型偶尔会带引号/前缀，做一次轻量清洗
        for junk in ("消息正文：", "回复：", "正文："):
            if text.startswith(junk):
                text = text[len(junk):].strip()
        return text.strip('"“”\n') or None

    async def _maybe_send(self, force: bool):
        """按开关/绑定/时段/上限/间隔五重条件决定是否生成并发送一条消息。"""
        if not self.config.get("ENABLE", True) and not force:
            return
        umo = self._target_umo()
        if not umo:
            return
        now = datetime.now()
        self._roll_daily_count(now)
        limit = max(1, int(self.config.get("DAILY_LIMIT", 3) or 3))
        min_gap = max(5, int(self.config.get("MIN_INTERVAL_MINUTES", 90) or 90)) * 60
        if not force:
            if not self._in_active_window(now):
                return
            if self._state["sent_today"] >= limit:
                return
            if time.time() - float(self._state.get("last_send_ts", 0) or 0) < min_gap:
                return
        text = await self._generate_message(force=force)
        if not text:
            logger.info("[主动伴聊] 本轮模型选择沉默（PASS）或生成失败，不发送")
            return
        ok = await self.context.send_message(umo, MessageChain([Plain(text)]))
        if not ok:
            logger.warning(f"[主动伴聊] 未找到会话对应的平台适配器，发送失败: {umo}")
            return
        self._state["sent_today"] = int(self._state.get("sent_today", 0)) + 1
        self._state["last_send_ts"] = time.time()
        self._push_recent("bot", text)
        self._save_state()
        logger.info(f"[主动伴聊] 已发送主动消息（今日第 {self._state['sent_today']} 条）: {text[:30]}...")

    # ───────────────────────────── 消息记录 ─────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_any_message(self, event: AstrMessageEvent):
        """记录绑定目标发来的文本，作为下次主动消息的上下文。不产生回复。"""
        umo = self._target_umo()
        if not umo or event.unified_msg_origin != umo:
            return
        texts = [c.message.strip() for c in event.message_chain if isinstance(c, Plain)]
        text = " ".join(t for t in texts if t).strip()
        if 0 < len(text) <= 500 and not text.startswith("/proactive"):
            self._push_recent("user", text)
            self._save_state()

    def _push_recent(self, role: str, text: str):
        recent = self._state.setdefault("recent", [])
        recent.append({"role": role, "text": text, "ts": int(time.time())})
        if len(recent) > RECENT_CAP:
            del recent[: len(recent) - RECENT_CAP]

    # ───────────────────────────── 命令 ─────────────────────────────

    @filter.command("proactive")
    async def command_main(self, event: AstrMessageEvent):
        """/proactive 绑定|解绑|状态|开|关|测试 —— 管理主动伴聊。"""
        raw = (event.get_message_str() or "").strip()
        parts = raw.split()
        sub = parts[1] if len(parts) > 1 else "状态"

        if sub in ("绑定", "bind"):
            self.config["TARGET_UMO"] = event.unified_msg_origin
            try:
                self.config.save_config()
            except Exception as exc:
                logger.warning(f"[主动伴聊] 配置持久化失败（本次会话内仍生效）: {exc}")
            yield event.plain_result(
                f"✅ 已绑定当前会话为主动消息目标。\nUMO: {event.unified_msg_origin}\n"
                "接下来用 /proactive 测试 试发一条吧~"
            )
        elif sub in ("解绑", "unbind"):
            self.config["TARGET_UMO"] = ""
            try:
                self.config.save_config()
            except Exception:
                pass
            yield event.plain_result("已解绑，不会再主动发消息。")
        elif sub in ("开", "on"):
            self.config["ENABLE"] = True
            try:
                self.config.save_config()
            except Exception:
                pass
            yield event.plain_result("主动消息已开启。")
        elif sub in ("关", "off"):
            self.config["ENABLE"] = False
            try:
                self.config.save_config()
            except Exception:
                pass
            yield event.plain_result("主动消息已关闭（/proactive 开 可恢复）。")
        elif sub in ("测试", "test"):
            if not self._target_umo():
                yield event.plain_result("还没绑定目标：先发 /proactive 绑定")
                return
            yield event.plain_result("正在让模型现编一条……稍等")
            try:
                await self._maybe_send(force=True)
                yield event.plain_result("若上面收到了新消息即测试成功（不受间隔/时段限制，但计入今日配额）。")
            except Exception as exc:
                yield event.plain_result(f"测试失败：{exc}")
        else:  # 状态
            now = datetime.now()
            self._roll_daily_count(now)
            target = self._target_umo() or "未绑定"
            window = f"{self.config.get('ACTIVE_START', '09:00')} ~ {self.config.get('ACTIVE_END', '23:00')}"
            last = self._state.get("last_send_ts", 0)
            last_s = datetime.fromtimestamp(last).strftime("%m-%d %H:%M") if last else "从未"
            yield event.plain_result(
                "【主动伴聊】\n"
                f"开关: {'开' if self.config.get('ENABLE', True) else '关'} | 目标: {target}\n"
                f"活跃时段: {window} | 今日已发: {self._state['sent_today']}/{self.config.get('DAILY_LIMIT', 3)}\n"
                f"最小间隔: {self.config.get('MIN_INTERVAL_MINUTES', 90)} 分钟 | 上次发送: {last_s}\n"
                f"子命令: 绑定 / 解绑 / 测试 / 开 / 关"
            )

    # ───────────────────────────── 状态持久化 ─────────────────────────────

    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._state.update(data)
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning(f"[主动伴聊] 状态文件读取失败，使用空状态: {exc}")

    def _save_state(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as exc:
            logger.warning(f"[主动伴聊] 状态保存失败: {exc}")
