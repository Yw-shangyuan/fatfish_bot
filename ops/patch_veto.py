
path = '/home/ubuntu/AstrBot/data/plugins/astrbot_plugin_bilibili_ai_bot/main.py'
src = open(path, encoding='utf-8').read()

# 1. remove debug probe
dbg = """        if is_group:
            logger.info(f"[gate-debug] sender={event.get_sender_id()} at_or_wake={event.is_at_or_wake_command} need_at={self.config.get('QQ_NEED_AT', False)} msg={str(event.message_str or '')[:30]!r}")
            if self._qq_quiet_window()[0]:"""
orig = """        if is_group:
            if self._qq_quiet_window()[0]:"""
assert dbg in src, 'debug probe not found'
src = src.replace(dbg, orig, 1)

# 2. add LLM veto at top of the on_llm_request hook
anchor = """        \"\"\"QQ对话自动注入B站侧记忆：永久记忆 + 语义检索相关记忆\"\"\"
        try:"""
veto = """        \"\"\"QQ对话自动注入B站侧记忆：永久记忆 + 语义检索相关记忆\"\"\"
        # 终极闸：群消息在静默时段、或要@模式下没@肥鱼，一律不许走到 LLM。
        # 入口闸的 stop_event 可能被未知路径绕过，这里在 LLM 调用点前再拦一次。
        # 命令消息以唤醒词 "/" 开头，is_at_or_wake_command 为 True，不受影响。
        try:
            if event.get_group_id() and event.get_platform_name() != "webchat":
                if self._qq_quiet_window()[0]:
                    logger.info("[BiliBot] LLM veto: group msg in quiet hours")
                    event.stop_event()
                    return
                if self.config.get("QQ_NEED_AT", False) and not event.is_at_or_wake_command:
                    logger.info(
                        f"[BiliBot] LLM veto: group msg without @ blocked "
                        f"(sender={event.get_sender_id()})"
                    )
                    event.stop_event()
                    return
        except Exception:
            pass
        try:"""
assert anchor in src, 'hook anchor not found'
src = src.replace(anchor, veto, 1)

open(path, 'w', encoding='utf-8').write(src)
print('patched: debug probe removed, LLM veto installed')
