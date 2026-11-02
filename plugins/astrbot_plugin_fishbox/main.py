# -*- coding: utf-8 -*-
"""鱼箱桥接：把本地工具沙箱接到 AstrBot 上，主干零改动。

设计原则：
- 只做转发，不做工具逻辑；工具跑在 fishbox_home 指向的独立沙箱进程里
- 工具命令仅管理员可用（AstrBot admins_id 或 FISHBOX_OWNER 覆盖），群里自动解码不受此限
- 沙箱失联就闭嘴：socket 连不上时只回一句，不抛异常、不影响机器人主干
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Node, Nodes, Plain

# 导入阶段找客户端用的目录：模块期拿不到面板配置，只能由环境变量或默认值决定
FISHBOX_DIR = os.environ.get("FISHBOX_DIR", "/home/ubuntu/fishbox")
# 主人 QQ 号覆盖项：无默认值，空串永不匹配，权限判定退回 is_admin()
OWNER_ID = os.environ.get("FISHBOX_OWNER", "")
TIMEOUT = 40.0

# 卡组码识别：AA 开头 + base64 字符集 + 长度够，前后不能粘连字母数字
DECK_RE = re.compile(r"(?<![A-Za-z0-9])AA[A-Za-z0-9+/]{38,220}(?![A-Za-z0-9])")
DECK_COOLDOWN = 60.0     # 同一个码在同一个群，60 秒内只回一次
DECK_GAP = 10.0          # 不同码之间，10 秒一次
DECK_HOURLY_CAP = 30     # 每小时最多解析 30 套，超了回提示
DECK_MAX_PER_MSG = 10    # 单条消息最多解析 10 套，多出来的提示分开发
_deck_seen: dict[tuple[str, str], float] = {}
_deck_hour: dict[str, list[float]] = {}
_cap_notice: dict[str, float] = {}

if FISHBOX_DIR not in sys.path:
    sys.path.insert(0, FISHBOX_DIR)

try:
    import client as fishbox_client  # noqa: E402
except Exception as exc:  # pragma: no cover
    fishbox_client = None
    logger.warning(f"[fishbox] 客户端导入失败：{exc}")


def _call_sync(payload: dict) -> dict:
    if fishbox_client is None:
        return {"ok": False, "error": "鱼箱客户端未加载"}
    try:
        return fishbox_client.call(payload, timeout=TIMEOUT)
    except FileNotFoundError:
        return {"ok": False, "error": "鱼箱没在跑（socket 不存在）"}
    except Exception as exc:
        return {"ok": False, "error": f"鱼箱调用异常：{exc}"}


async def _call(payload: dict) -> dict:
    return await asyncio.to_thread(_call_sync, payload)


@register(
    "astrbot_plugin_fishbox",
    "FatFish",
    "鱼箱桥接：群里按需调用本地工具，工具跑在独立沙箱进程",
    "0.2.0",
)
class FishboxBridge(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 沙箱连接路径优先级：环境变量 > 面板配置 > 默认值。
        # 真正发起连接的是薄客户端模块级 SOCK，所以解析完覆盖回它身上。
        home = os.environ.get("FISHBOX_DIR") or self.config.get("fishbox_home") or "/home/ubuntu/fishbox"
        sock = (
            os.environ.get("FISHBOX_SOCK")
            or self.config.get("socket_path")
            or os.path.join(home, "fishbox.sock")
        )
        if fishbox_client is not None:
            fishbox_client.SOCK = Path(sock)

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        """管理员判定：优先 AstrBot 全局 admins_id，其次可选的 FISHBOX_OWNER 覆盖号。"""
        if event.is_admin():
            return True
        uid = str(event.get_sender_id() or "")
        return bool(OWNER_ID) and uid == OWNER_ID

    def _mentions_me(self, event: AstrMessageEvent) -> bool:
        """群里是否 @ 了本鱼（或命中唤醒前缀）。"""
        if event.is_wake_up():
            return True
        sid = str(event.get_self_id() or "")
        if not sid:
            return False
        for comp in event.get_messages():
            if comp.__class__.__name__ == "At" and str(getattr(comp, "qq", "")) == sid:
                return True
        return False

    def _deck_batch(self, group: str, codes: list[str]) -> tuple[list[str], str]:
        """一批码一次性放闸，供同一条消息里的多个卡组码共用。

        批内不再要求 DECK_GAP 间隔（同一条消息本来就是同时到达的），
        跨批仍然要求；每放行一套占一小时额度一格。

        Args:
            group: 群号，私聊时回退成 QQ 号。
            codes: 本条消息去重并截断到上限后的卡组码，按出现顺序。

        Returns:
            (放行的码, 判定)，判定为 ok / skip / cap。
        """
        now = time.time()
        bucket = [t for t in _deck_hour.get(group, []) if now - t < 3600]
        _deck_hour[group] = bucket
        if bucket and now - bucket[-1] < DECK_GAP:
            return [], "skip"      # 上一条消息刚解过，整批先按住
        if len(bucket) >= DECK_HOURLY_CAP:
            return [], "cap"
        room = DECK_HOURLY_CAP - len(bucket)
        accepted = []
        for code in codes:
            if len(accepted) >= room:
                break              # 这一小时的额度只剩这么多
            if now - _deck_seen.get((group, code), 0) < DECK_COOLDOWN:
                continue           # 同一个码，一分钟内不重复解
            _deck_seen[(group, code)] = now
            accepted.append(code)
        if not accepted:
            return [], "skip"
        bucket.extend([now] * len(accepted))
        if len(_deck_seen) > 500:  # 清一清老记录，别让内存长草
            for k in [k for k, t in _deck_seen.items() if now - t > 3600]:
                _deck_seen.pop(k, None)
        return accepted, "ok"

    def _cap_left(self, group: str) -> int:
        """冷却还剩多少秒：最早那条记录出窗口的时间。"""
        bucket = _deck_hour.get(group) or []
        if not bucket:
            return 0
        return max(0, int(bucket[0] + 3600 - time.time()))

    def _format_deck(self, result: dict) -> str:
        hero = result.get("hero") or "未知英雄"
        cards = result.get("cards") or []
        total = result.get("total") or sum(c.get("count", 0) for c in cards)
        # 只报职业，英雄名对读卡组的人没有信息量；查不到职业时退回英雄名，避免空标题
        lines = [f"{result.get('hero_class') or hero} · {total} 张"]
        for c in cards:
            cost = "?" if c.get("cost") is None else c.get("cost")
            cnt = c.get("count", 1)
            line = f"{cost}费 {c.get('name', '?')}"
            if cnt > 1:
                line += f" ×{cnt}"
            lines.append(line)
        text = "\n".join(lines)
        cap = int(self.config.get("max_deck_text", 900))
        return text if len(text) <= cap else text[:cap] + "\n…（太长，先说这么多）"

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def auto_deck_code(self, event: AstrMessageEvent):
        """群里被 @ 时，消息里带卡组码就自动解码。"""
        if not self._mentions_me(event):
            return
        text = event.get_message_str() or ""
        codes = []
        for m in DECK_RE.finditer(text):
            code = m.group(0)
            if len(set(code)) < 10:  # 一串 A 之类的噪音，直接当没看见
                continue
            if code not in codes:    # 同一条消息里重复贴的码只解一次
                codes.append(code)
        if not codes:
            return
        overflow = max(0, len(codes) - DECK_MAX_PER_MSG)
        codes = codes[:DECK_MAX_PER_MSG]
        group = str(event.get_group_id() or event.get_sender_id() or "")
        codes, verdict = self._deck_batch(group, codes)
        if verdict == "skip":
            return
        if verdict == "cap":
            now = time.time()
            if now - _cap_notice.get(group, 0) < 60:   # 上限提示自己也限流，别刷
                return
            _cap_notice[group] = now
            left = self._cap_left(group)
            until = time.strftime("%H:%M", time.localtime(now + left))
            yield event.plain_result(
                f"当时段解析卡组打到上限，冷却时间至：{until}（约 {max(1, left // 60)} 分钟后恢复）"
            )
            event.stop_event()
            return

        # 顺序解码不并发：每次调用都会起独立进程去解析 10MB 卡表，并发会压垮小机器
        results = []
        for code in codes:
            resp = await _call({"action": "run", "tool": "hearthstone_deck", "args": {"code": code}})
            if resp.get("ok"):
                results.append(resp.get("result") or {})
            else:
                results.append({"_err": resp.get("error", "未知错误")})

        if len(results) == 1 and not overflow:
            # 只有一套时保持原样：纯文本直发，不套合并转发
            one = results[0]
            if "_err" in one:
                yield event.plain_result(f"卡组码没解开：{one['_err']}")
            else:
                yield event.plain_result(self._format_deck(one))
            event.stop_event()
            return

        me = str(event.get_self_id() or "0")
        nodes = []
        for res in results:
            if "_err" in res:
                nodes.append(Node(name="解析失败", uin=me,
                                  content=[Plain(text=f"卡组码没解开：{res['_err']}")]))
                continue
            title = res.get("hero_class") or res.get("hero") or "卡组"
            nodes.append(Node(name=title[:20], uin=me,
                              content=[Plain(text=self._format_deck(res))]))
        if overflow:
            nodes.append(Node(name="提示", uin=me, content=[Plain(
                text=f"一条消息最多解 {DECK_MAX_PER_MSG} 套，另有 {overflow} 套请分开发。")]))
        chain = event.make_result()
        chain.chain.append(Nodes(nodes))   # 适配器识别到 Nodes 会改走 send_group_forward_msg
        yield chain
        event.stop_event()

    @filter.command("鱼箱列表")
    async def list_tools(self, event: AstrMessageEvent):
        """列出沙箱里可用的工具。"""
        if not self._is_owner(event):
            return
        resp = await _call({"action": "list"})
        if not resp.get("ok"):
            yield event.plain_result(f"鱼箱不在线：{resp.get('error', '未知错误')}")
            return
        rows = [f"{t['name']} — {t.get('description', '')}" for t in resp.get("result", [])]
        yield event.plain_result("鱼箱工具：\n" + ("\n".join(rows) or "（空的）"))

    @filter.command("鱼箱")
    async def run_tool(self, event: AstrMessageEvent, tool: str = "", args: str = ""):
        """调用工具：/鱼箱 工具名 {"key":"value"}"""
        if not self._is_owner(event):
            return
        name = (tool or "").strip()
        if not name:
            yield event.plain_result("用法：/鱼箱 工具名 {\"参数\":\"值\"}，看清单用 /鱼箱列表")
            return
        payload = {}
        raw = (args or "").strip()
        if raw:
            try:
                payload = json.loads(raw)
            except ValueError:
                yield event.plain_result("参数得是 JSON，比如 {\"code\":\"AAECAf7g...\"}")
                return
            if not isinstance(payload, dict):
                yield event.plain_result("参数得是 JSON 对象")
                return
        resp = await _call({"action": "run", "tool": name, "args": payload})
        if not resp.get("ok"):
            yield event.plain_result(f"调用失败：{resp.get('error', '未知错误')}")
            return
        text = json.dumps(resp.get("result"), ensure_ascii=False)
        cap = int(self.config.get("max_tool_output", 1500))
        if len(text) > cap:
            text = text[:cap] + " …（截断）"
        yield event.plain_result(text)

    async def terminate(self):
        """插件卸载时不做任何清理，沙箱是独立进程。"""
        logger.info("[fishbox] 桥接插件已卸载，沙箱进程不受影响")
