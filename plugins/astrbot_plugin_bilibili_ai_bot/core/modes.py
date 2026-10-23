"""模式系统：把人格文本与行为参数打包成可用 QQ 指令切换的预设。

AstrBot agent 每轮对话都按 persona_id 实时解析人格（见 persona_mgr），
所以"切换模式" = 用官方 API 热替换该人格的 system_prompt，再把模式自带
的白名单配置覆盖应用到插件 config。未激活的模式只是磁盘上的 JSON，零
token 开销；切换即时生效，无需重启。
"""
from __future__ import annotations

import json
import os

from astrbot.api import logger

from .config import DATA_DIR

#: 模式文件允许覆盖的 config 键；名单外的键一律忽略并告警。
MODE_OVERRIDE_WHITELIST = {"BILI_SHARE_PARSE_AUTO_TRIGGER_ENABLED"}

#: agent_runner 引用的 AstrBot 人格名（可经 MODE_PERSONA_ID 配置改绑）。
DEFAULT_MODE_PERSONA_ID = "宇文尚元的蓝色大肥鱼"


class ModeMixin:
    """BiliBiliBot 的模式加载与切换，混入主插件类使用。"""

    def _modes_dirs(self):
        """返回模式文件目录：插件自带 modes/ 在前，plugin_data/modes/ 同名覆盖。"""
        builtin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modes")
        override = os.path.join(DATA_DIR, "modes")
        return [d for d in (builtin, override) if os.path.isdir(d)]

    def _modes_load(self, refresh=False):
        """加载全部模式定义，返回 {key: cfg}。默认走内存缓存，refresh 强制重读。

        Args:
            refresh: True 时忽略缓存重新扫描磁盘。

        Returns:
            dict[str, dict]: 模式 key 到定义的映射，缺 persona 的文件被跳过。
        """
        if not refresh and getattr(self, "_modes_cache", None) is not None:
            return self._modes_cache
        modes = {}
        for d in self._modes_dirs():
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        cfg = json.load(f)
                    key = str(cfg.get("key") or fn[:-5]).strip().lower()
                    if key and isinstance(cfg.get("persona"), dict):
                        modes[key] = cfg
                except Exception as exc:
                    logger.warning(f"[BiliBot] 模式文件加载失败 {fn}: {exc}")
        self._modes_cache = modes
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

    def _current_mode_key(self):
        return str(self.config.get("CURRENT_MODE", "normal") or "normal").strip().lower()

    def _mode_owner_gate_enabled(self):
        """主人消息闸门只在 owner_gate 开启的模式下生效（默认常规模式）。"""
        mode = self._modes_load().get(self._current_mode_key())
        if mode is None:
            return self._current_mode_key() == "normal"
        return bool(mode.get("owner_gate", False))

    async def _mode_apply(self, key):
        """切换到指定模式：热换 AstrBot 人格 + 应用白名单覆盖 + 记录当前模式。

        Args:
            key: 模式 key（需已由 _mode_find 解析）。

        Returns:
            str: 给用户看的切换结果文案。
        """
        modes = self._modes_load(refresh=True)
        mode = modes.get(key)
        if not mode:
            return f"未知模式：{key}"
        prompt = str((mode.get("persona") or {}).get("system_prompt") or "").strip()
        persona_id = str(self.config.get("MODE_PERSONA_ID", "") or DEFAULT_MODE_PERSONA_ID).strip()
        notes = []
        if prompt:
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
        for k, v in (mode.get("overrides") or {}).items():
            if k in MODE_OVERRIDE_WHITELIST:
                self.config[k] = v
                changed.append(f"{k}={v}")
            else:
                logger.warning(f"[BiliBot] 模式「{mode.get('name')}」尝试覆盖非白名单键 {k}，已忽略")
        self.config["CURRENT_MODE"] = key
        self.config.save_config()
        self._modes_cache = None
        line = f"已切换到「{mode.get('name') or key}」"
        if notes:
            line += "（" + "，".join(notes) + "）"
        if changed:
            line += "\n行为覆盖：" + "，".join(changed)
        return line
