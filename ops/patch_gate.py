
path = '/home/ubuntu/AstrBot/data/plugins/astrbot_plugin_bilibili_ai_bot/main.py'
src = open(path, encoding='utf-8').read()
anchor = """        if is_group:
            if self._qq_quiet_window()[0]:"""
inject = """        if is_group:
            logger.info(f"[gate-debug] sender={event.get_sender_id()} at_or_wake={event.is_at_or_wake_command} need_at={self.config.get('QQ_NEED_AT', False)} msg={str(event.message_str or '')[:30]!r}")
            if self._qq_quiet_window()[0]:"""
assert anchor in src, 'anchor not found'
assert '[gate-debug]' not in src, 'already patched'
open(path, 'w', encoding='utf-8').write(src.replace(anchor, inject, 1))
print('patched')
