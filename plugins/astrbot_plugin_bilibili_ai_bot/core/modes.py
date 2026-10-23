"""模式系统：QQ 与 B站 两侧互相独立的模式库。

QQ 侧（/qq模式）：热换 AstrBot 人格（persona_mgr 每轮按名字实时解析）
+ 白名单行为覆盖，即时生效、零重启、未激活模式零 token。
B站侧（/bili模式）：覆盖 CUSTOM_SYSTEM_PROMPT / CUSTOM_REPLY_INSTRUCTION
两键文案；BiliBot 生成评论回复时实时读 config，覆盖即时生效。

模式文件是普通 JSON：插件自带 modes/<side>/，plugin_data/modes/<side>/
放同名文件可覆盖、放新文件即新增自定义模式。
"""
from __future__ import annotations

import json
import os

from astrbot.api import logger

from .config import DATA_DIR

#: 各侧模式文件允许覆盖的 config 键；名单外的键一律忽略并告警。
MODE_OVERRIDE_WHITELIST = {
    "qq": {"BILI_SHARE_PARSE_AUTO_TRIGGER_ENABLED"},
    "bili": {"CUSTOM_SYSTEM_PROMPT", "CUSTOM_REPLY_INSTRUCTION"},
}

#: agent_runner 引用的 AstrBot 人格名（可经 MODE_PERSONA_ID 配置改绑）。
DEFAULT_MODE_PERSONA_ID = "宇文尚元的蓝色大肥鱼"


class ModeMixin:
    """BiliBiliBot 的双侧模式加载与切换，混入主插件类使用。"""

    def _modes_dir(self, side):
        """返回某侧的模式目录：自带 modes/<side>/ 在前，plugin_data 同名覆盖。"""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        builtin = os.path.join(base, "modes", side)
        override = os.path.join(DATA_DIR, "modes", side)
        return [d for d in (builtin, override) if os.path.isdir(d)]

    def _modes_load(self, side, refresh=False):
        """加载某侧全部模式定义，返回 {key: cfg}。默认走缓存，refresh 强制重读。

        Args:
            side: "qq" 或 "bili"。
            refresh: True 时忽略缓存重新扫描磁盘。

        Returns:
            dict[str, dict]: 模式 key 到定义的映射；persona 与 overrides 都缺的
            文件被跳过。
        """
        cache = getattr(self, "_modes_cache", None)
        if cache is None:
            cache = self._modes_cache = {}
        if not refresh and side in cache:
            return cache[side]
        modes = {}
        for d in self._modes_dir(side):
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        cfg = json.load(f)
                    key = str(cfg.get("key") or fn[:-5]).strip().lower()
                    if key and (isinstance(cfg.get("persona"), dict) or isinstance(cfg.get("overrides"), dict)):
                        modes[key] = cfg
                except Exception as exc:
                    logger.warning(f"[BiliBot] 模式文件加载失败 {side}/{fn}: {exc}")
        cache[side] = modes
        return modes

    def _mode_find(self, modes, word):
        """按 key/名称/别名匹配模式，精确优先、其次前缀。找不到返回 None。"""
        w = str(word or "").strip().lower()
        if not w:
            return None

        def all_names(key, cfg):
            return [key.lower(), str(cfg.get("name") or "").lower()] + [str(a).lower() for a in cfg.get("aliases") or []]

        for key, cfg in modes.items():
            if w in all_names(key, cfg):
                return key
        for key, cfg in modes.items():
            if any(n and n.startswith(w) for n in all_names(key, cfg)):
                return key
        return None

    def _current_mode_key(self, side):
        """当前模式 key。QQ 侧兼容迁移旧版单键 CURRENT_MODE。"""
        key = str(self.config.get(f"{side.upper()}_MODE", "") or "").strip().lower()
        if not key and side == "qq":
            key = str(self.config.get("CURRENT_MODE", "") or "").strip().lower()
        return key or "normal"

    def _mode_owner_gate_enabled(self):
        """主人消息闸门只在 QQ 侧 owner_gate 开启的模式下生效（默认常规模式）。"""
        mode = self._modes_load("qq").get(self._current_mode_key("qq"))
        if mode is None:
            return self._current_mode_key("qq") == "normal"
        return bool(mode.get("owner_gate", False))

    async def _mode_apply(self, side, key):
        """切换某侧模式：QQ 侧热换人格，B站 侧覆盖两键；记录状态并落盘。

        Args:
            side: "qq" 或 "bili"。
            key: 已解析的模式 key。

        Returns:
            str: 给用户看的切换结果文案。
        """
        modes = self._modes_load(side, refresh=True)
        mode = modes.get(key)
        if not mode:
            return f"未知模式：{key}"
        notes = []
        if side == "qq":
            prompt = str((mode.get("persona") or {}).get("system_prompt") or "").strip()
            if prompt:
                persona_id = str(self.config.get("MODE_PERSONA_ID", "") or DEFAULT_MODE_PERSONA_ID).strip()
                pm = getattr(self.context, "persona_manager", None)
                if pm is None:
                    return "当前 AstrBot 未提供人格管理，无法热换人格。"
                try:
                    await pm.update_persona(persona_id, system_prompt=prompt)
                    notes.append("人格已换")
                except ValueError:
                    # 人格被删过就按模式文案重建，保证切模式总能成功
                    try:
                        await pm.create_persona(persona_id, prompt)
                        notes.append(f"人格「{persona_id}」不存在，已按模式文案创建")
                    except Exception as exc:
                        return f"人格更新失败：{exc}"
                except Exception as exc:
                    return f"人格更新失败：{exc}"
        changed = []
        whitelist = MODE_OVERRIDE_WHITELIST.get(side, set())
        for k, v in (mode.get("overrides") or {}).items():
            if k in whitelist:
                self.config[k] = v
                changed.append(k)
            else:
                logger.warning(f"[BiliBot] 模式「{mode.get('name')}」尝试覆盖非白名单键 {k}，已忽略")
        self.config[f"{side.upper()}_MODE"] = key
        self.config.save_config()
        self._modes_cache = None
        line = f"已切换到「{mode.get('name') or key}」"
        if notes:
            line += "（" + "，".join(notes) + "）"
        if changed:
            line += "\n行为覆盖：" + "，".join(changed)
        return line

    async def _modes_command_text(self, event, side):
        """处理 /qq模式 与 /bili模式 的共用文案：无参列模式，带参切换。"""
        parts = event.message_str.strip().split(maxsplit=1)
        modes = self._modes_load(side, refresh=True)
        cur = self._current_mode_key(side)
        label = "🐳 QQ 聊天" if side == "qq" else "📺 B站"
        cmd = "/qq模式" if side == "qq" else "/bili模式"
        if len(parts) < 2:
            lines = [f"{label} 可切换的模式："]
            for k, cfg in modes.items():
                mark = "  ← 当前" if k == cur else ""
                lines.append(f"  {cfg.get('name') or k}{mark}")
                if cfg.get("desc"):
                    lines.append(f"    {cfg['desc']}")
            lines += ["", f"用法: {cmd} <模式名>"]
            return "\n".join(lines)
        key = self._mode_find(modes, parts[1])
        if not key:
            names = "、".join(str(c.get("name") or k) for k, c in modes.items())
            return f"❌ 不认识的模式：{parts[1]}\n可选项：{names}"
        return await self._mode_apply(side, key)
