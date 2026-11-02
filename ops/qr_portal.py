#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fat fish mini control panel (stdlib only, one tokened page).

Sections: login status + QR image + restart-login button, and mute gates.
A mute gate is a file holding an epoch deadline; absent/expired = open.
To extend: add a row to GATES or OFF_SECONDS, or a name->callable entry to
EXTRA_ACTIONS, and it shows up as a button automatically.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
DROP_DIR = "/home/ubuntu/ops/drop"
DROP_MINUTES = 20
DROP_LOG = "/home/ubuntu/ops/drop/access.log"
TOKEN_FILE = os.path.expanduser("~/.config/fatfish-qr/token")
MUTE_DIR = os.path.expanduser("~/.config/fatfish-sentinel")
KIT_DIR = "/home/ubuntu/ops/kit"
GRAB_SH = "/home/ubuntu/ops/grab-screen.sh"
QR_PNG = "/tmp/fish_qr.png"
_grab_lock = threading.Lock()
GATES = {  # key -> (label, file, action prefix uses key)
    "qq": ("QQ 闸门（消息全哑，零 token）", MUTE_DIR + "/qq_mute"),
    "bili": ("B站闸门（动作全停，零 token）", MUTE_DIR + "/bili_mute"),
}
OFF_SECONDS = [("30分", 1800), ("2时", 7200), ("8时", 28800), ("24时", 86400)]
EXTRA_ACTIONS = {}  # name -> callable(); add future buttons here

LOGIN_API = "http://127.0.0.1:3000/get_login_info"
ONEBOT_CFG = "/srv/snowluma/data/config/onebot.json"
RESTART_COOLDOWN = 60.0
_state = {"last_restart": 0.0, "note": ""}


def read_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def login_info():
    """Return (online, user_id, nickname) from OneBot get_login_info."""
    headers = {"Content-Type": "application/json"}
    try:  # SnowLuma auto-generates a Bearer token; follow it from config
        with open(ONEBOT_CFG, "r", encoding="utf-8") as f:
            srv = (json.load(f).get("networks", {}).get("httpServers") or [{}])[0]
        tok = srv.get("accessToken") or ""
        if tok:
            headers["Authorization"] = "Bearer " + tok
    except Exception:
        pass
    try:
        req = urllib.request.Request(LOGIN_API, data=b"{}", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        if body.get("retcode") == 0:
            d = body.get("data") or {}
            return True, d.get("user_id") or "?", d.get("nickname") or "?"
    except Exception:
        pass
    return False, None, None


def read_mute(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            until = float(f.readline().strip())
        return until if until > time.time() else None
    except (OSError, ValueError):
        return None


def arm_mute(path, seconds):
    os.makedirs(MUTE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(time.time() + seconds))
    os.chmod(path, 0o600)


def disarm_mute(path):
    try:
        os.remove(path)
    except OSError:
        pass


def hms(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def restart_protocol():
    left = RESTART_COOLDOWN - (time.time() - _state["last_restart"])
    if left > 0:
        return f"冷却中，请 {int(left)}s 后再试"
    _state["last_restart"] = time.time()
    subprocess.Popen(
        ["docker", "restart", "-t", "5", "snowluma"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "已重启（约40秒）。注意：若重启前在线且未勾选自动登录，需重新扫码"


def grab_qr():
    """Click virtual refresh + screenshot via the server grabber; return png.

    Returns:
        PNG bytes on success, None when the grabber or file is unavailable.
    """
    with _grab_lock:
        subprocess.run(
            ["bash", GRAB_SH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        try:
            with open(QR_PNG, "rb") as f:
                return f.read()
        except OSError:
            return None


def run_action(name, form):
    """Dispatch a button name. Returns a short note shown on the page."""
    parts = name.split("_")
    if parts and parts[0] == "off" and parts[1] in GATES:
        path = GATES[parts[1]][1]
        if len(parts) == 3 and parts[2] == "custom":
            try:
                hours = min(720.0, max(0.02, float(form.get("hours_" + parts[1], "0"))))
            except ValueError:
                return "自定义时长无效"
            arm_mute(path, hours * 3600)
            return f"已关闭，{hours:g} 小时后自动放行"
        if len(parts) == 3:
            arm_mute(path, int(parts[2]))
            return f"已关闭，{hms(int(parts[2]))} 后自动放行"
    if len(parts) == 2 and parts[0] == "on" and parts[1] in GATES:
        disarm_mute(GATES[parts[1]][1])
        return "已开闸"
    if name == "restart":
        return restart_protocol()
    if name in EXTRA_ACTIONS:
        return str(EXTRA_ACTIONS[name]())
    return "未知动作"


def gate_card(key):
    """All controls always visible: clicking any 关 while armed just re-arms."""
    label, path = GATES[key]
    until = read_mute(path)
    if until:
        status = f"🔴 关闭中 · 剩余 <b>{hms(until - time.time())}</b>"
    else:
        status = "🟢 开启中（一切照常）"
    buttons = "".join(
        f'<button name="act" value="off_{key}_{sec}" form="panel">关 {lab}</button>'
        for lab, sec in OFF_SECONDS
    )
    buttons += f'<input name="hours_{key}" size="3" placeholder="时"><button name="act" value="off_{key}_custom" form="panel">关N时</button>'
    buttons += f'<button name="act" value="on_{key}" form="panel">🟢 开闸</button>'
    return f'<div class="card"><div class="t">{label}</div><div>{status}</div><div class="b">{buttons}</div></div>'


def tools_card(token):
    """Download links for the server-side kit mirror (/home/ubuntu/ops/kit)."""
    try:
        names = sorted(
            n for n in os.listdir(KIT_DIR) if os.path.isfile(os.path.join(KIT_DIR, n))
        )
    except OSError:
        names = []
    links = "".join(
        f'<a href="/{token}/tools/{urllib.parse.quote(n)}" '
        f'style="color:#7fd4ff;margin:3px 10px 3px 0;display:inline-block">{n}</a>'
        for n in names
    )
    return (
        '<div class="card"><div class="t">工具下载（服务器镜像）</div>'
        f"<div>{links or '（kit 目录为空）'}</div></div>"
    )


def page(token, note):
    online, uid, nick = login_info()
    dot = f"🟢 在线 · {nick}（{uid}）" if online else "⚪ 离线"
    login_card = '<div class="card"><div class="t">登录</div>'
    if online:
        login_card += "<div>肥鱼在线，无需登录</div>"
    else:
        login_card += (
            "<div>离线待扫码：点「取最新码」（服务器会自动点刷新再截图），"
            "手机 QQ 对准扫图即可。<br>图约 1 分钟过期，过期就回到面板再点一次。"
            "</div>"
            f'<div class="b"><a href="/{token}/qr.png" target=_blank>'
            '<button type=button>📷 取最新码</button></a>'
            '<button name="act" value="restart" form="panel">'
            "🔁 重启 SnowLuma 换码</button></div>"
        )
    login_card += "</div>"
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        '<meta http-equiv="refresh" content="10">'
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>肥鱼中控</title><style>"
        "body{font-family:sans-serif;background:#101820;color:#dfe8ef;margin:10px}"
        ".card{background:#1b2733;border-radius:12px;padding:12px;margin:10px 0}"
        ".t{font-weight:bold;color:#7fd4ff;margin-bottom:6px}"
        ".b{margin-top:8px}"
        "button{background:#2d7dd2;color:#fff;border:0;border-radius:8px;"
        "padding:8px 12px;margin:3px;font-size:15px}"
        "input{padding:7px;border-radius:8px;border:0;margin:3px}"
        ".note{background:#3a2f1b;border-radius:8px;padding:8px;color:#ffd479}"
        "</style></head><body>"
        '<form id="panel" method="post" action="/' + token + '/act">'
        + f'<div class="card"><div class="t">🐳 肥鱼中控</div><div>状态：{dot}</div></div>'
        + gate_card("qq")
        + gate_card("bili")
        + login_card
        + drops_card()
        + tools_card(token)
        + note_html
        + "<input type=hidden name=act value=></form></body></html>"
    )


def drop_meta(d):
    try:
        with open(os.path.join(d, ".meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def drop_active(token):
    """Return meta dict when the drop is alive, else None."""
    token = token or ""
    if not re.fullmatch(r"[0-9a-f]{16,64}", token):
        return None
    d = os.path.join(DROP_DIR, token)
    m = drop_meta(d)
    if not m:
        return None
    try:
        exp = float(m.get("expires", 0))
    except (TypeError, ValueError):
        return None
    return m if exp > time.time() else None


def drop_cleanup():
    """Delete expired drop folders; loop forever in a daemon thread."""
    os.makedirs(DROP_DIR, exist_ok=True)
    while True:
        try:
            for n in os.listdir(DROP_DIR):
                d = os.path.join(DROP_DIR, n)
                if not os.path.isdir(d):
                    continue
                m = drop_meta(d)
                try:
                    exp = float(m.get("expires", 0)) if m else 0
                except (TypeError, ValueError):
                    exp = 0
                if exp <= time.time():
                    shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
        time.sleep(30)


def drop_log(ip, token, name, code, sent):
    try:
        with open(DROP_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} {ip} {token[:8]}… "
                f"{name} {code} {sent}B\n"
            )
    except OSError:
        pass


def drops_card():
    """Active drop links with remaining time."""
    try:
        names = sorted(os.listdir(DROP_DIR))
    except OSError:
        names = []
    now = time.time()
    rows = []
    for n in names:
        d = os.path.join(DROP_DIR, n)
        if not os.path.isdir(d):
            continue
        m = drop_meta(d)
        if not m:
            continue
        try:
            left = float(m.get("expires", 0)) - now
        except (TypeError, ValueError):
            continue
        if left <= 0:
            continue
        fn = m.get("name") or ""
        rows.append(
            f'<div>{fn} · 剩 {int(left // 60)}分{int(left % 60)}秒 · '
            f'<a href="/f/{n}/{urllib.parse.quote(fn)}" style="color:#7fd4ff">下载</a></div>'
        )
    return (
        '<div class="card"><div class="t">临时下载口（20 分钟自动删）</div>'
        + ("".join(rows) or "<div>（当前没有活动中的文件）</div>")
        + "</div>"
    )


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _route(self):
        """Return the sub-path after the token, or None when token is wrong."""
        tail = self.path.lstrip("/")
        if tail == self.token:
            return ""
        if tail.startswith(self.token + "/"):
            return tail[len(self.token) + 1 :]
        return None

    def _err(self, code, msg):
        self._send(code, msg, "text/plain; charset=utf-8")

    def serve_drop(self, token, filename):
        """Stream one file from a live drop folder, with Range support."""
        meta = drop_active(urllib.parse.unquote(token))
        if not meta:
            self._err(410, "链接已过期或不存在")
            return
        name = os.path.basename(urllib.parse.unquote(filename or ""))
        path = os.path.join(DROP_DIR, token, name)
        if not name or not os.path.isfile(path):
            self._err(404, "not found")
            return
        size = os.path.getsize(path)
        disp = urllib.parse.quote(meta.get("name") or name)
        head = self.command == "HEAD"
        start, end, code = 0, size - 1, 200
        rng = (self.headers.get("Range") or "").strip()
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng) if rng else None
        if m and size > 0 and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
                end = size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{disp}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            drop_log(self.client_address[0], token, name, code, 0)
            return
        sent = 0
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        drop_log(self.client_address[0], token, name, code, sent)

    def do_GET(self):
        raw = self.path.split("?", 1)[0]
        if raw.startswith("/f/"):
            tok, _, fn = raw[3:].partition("/")
            self.serve_drop(tok, fn)
            return
        route = self._route()
        if route is None:
            self._send(404, "not found", "text/plain")
            return
        if route == "qr.png":
            img = grab_qr()
            if img is None:
                self._send(503, "取码失败：截图流程没跑通", "text/plain; charset=utf-8")
            else:
                self._send(200, img, "image/png")
            return
        if route.startswith("tools/"):
            path = os.path.join(KIT_DIR, os.path.basename(route[6:]))
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            else:
                self._send(404, "not found", "text/plain")
            return
        if route:
            self._send(404, "not found", "text/plain")
            return
        self._send(200, page(self.token, _state.get("note", "")))
        _state["note"] = ""

    def do_HEAD(self):
        raw = self.path.split("?", 1)[0]
        if not raw.startswith("/f/"):
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        tok, _, fn = raw[3:].partition("/")
        self.serve_drop(tok, fn)

    def do_POST(self):
        route = self._route()
        if route not in ("act", "act/_"):
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        name = form.get("act", "").strip()
        if name.endswith("_"):
            name = name.rstrip("_")
        note = run_action(name, form)
        _state["note"] = note
        self.send_response(303)
        self.send_header("Location", "/" + self.token)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    Handler.token = read_token()
    os.makedirs(DROP_DIR, exist_ok=True)
    threading.Thread(target=drop_cleanup, daemon=True).start()
    print(f"fatfish panel on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
