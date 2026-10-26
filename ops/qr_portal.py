#!/usr/bin/env python3
"""FatFish QR login portal: token-gated page serving the live NapCat login QR.

Serves at http://HOST:8765/<TOKEN> - auto-refreshes every 15s so the phone
always sees the freshest QR (NapCat regenerates qrcode.png every ~2 min).
While the account is online the page shows status only and never leaks QR.
If the QR went stale (NapCat login loop died), a restart button (POST) runs
`docker restart napcat` to revive it - rate-limited, token-gated, hardcoded
command only. Wrong/missing token -> bare 404. Token lives outside the repo:
/home/ubuntu/.config/fatfish-qr/token (mode 600).
"""
import http.server
import json
import subprocess
import time
import html
import urllib.request

PORT = 8765
TOKEN_FILE = "/home/ubuntu/.config/fatfish-qr/token"
RESTART_COOLDOWN_SEC = 60

with open(TOKEN_FILE, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()

_state = {"last_restart": 0.0}


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True).stdout


def login_ok():
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:3000/get_login_info",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        d = json.loads(urllib.request.urlopen(req, timeout=6).read())
        return d.get("retcode") == 0
    except Exception:
        return False


def qr_age_sec():
    out = subprocess.run(
        ["docker", "exec", "napcat", "stat", "-c", "%Y", "/app/napcat/cache/qrcode.png"],
        capture_output=True,
    )
    try:
        return max(0, int(time.time()) - int(out.stdout.decode().strip()))
    except Exception:
        return -1


def qr_png():
    out = subprocess.run(
        ["docker", "exec", "napcat", "cat", "/app/napcat/cache/qrcode.png"],
        capture_output=True,
    )
    if out.returncode == 0 and out.stdout[:8] == b"\x89PNG\r\n\x1a\n":
        return out.stdout
    return None


def txz_link(max_age_sec=110):
    """Latest txz login link, accepted only if the QR that produced it is fresh."""
    if not (0 <= qr_age_sec() <= max_age_sec):
        return ""
    s = sh("docker logs --since 30m napcat 2>&1 | grep -aoE 'https://txz.qq.com[^ ]+' | tail -1")
    s = s.decode("ascii", "ignore").strip()
    return s if s.startswith("https://txz.qq.com/") else ""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", loc=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if loc:
            self.send_header("Location", loc)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/" + TOKEN + "/restart":
            return self._send(404, b"404 Not Found", "text/plain")
        now = time.time()
        left = int(RESTART_COOLDOWN_SEC - (now - _state["last_restart"]))
        if left > 0:
            return self._send(429, f"刚重启过，请 {left} 秒后再点".encode("utf-8"))
        _state["last_restart"] = now
        subprocess.run(["docker", "restart", "-t", "5", "napcat"], capture_output=True, timeout=60)
        # give NapCat a moment to come back, then the page reloads itself
        return self._send(200, "<meta http-equiv='refresh' content='12;url={}'>正在重启 NapCat 登录流程（约10~30秒），稍候自动返回...".format("/" + TOKEN).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/" + TOKEN, "/" + TOKEN + "/", "/" + TOKEN + "/img"):
            return self._send(404, b"404 Not Found", "text/plain")
        if login_ok():
            return self._send(200, "<h2>&#128994; 肥鱼在线中，无需登录</h2><p>页面每 60 秒自动刷新。</p>".encode("utf-8"))
        if path == "/" + TOKEN + "/img":
            png = qr_png()
            return self._send(200, png, "image/png") if png else self._send(404, b"no qr", "text/plain")
        age = qr_age_sec()
        fresh = 0 <= age < 110
        link = txz_link()
        qr_html = '<img src="/{}/img?n={}" width="260" height="260" style="border:1px solid #ccc;border-radius:8px">'.format(TOKEN, int(time.time())) if age >= 0 else "<p>暂无二维码文件</p>"
        if link:
            main_html = '<a href="{}" style="display:inline-block;margin:12px 0;padding:14px 26px;background:#12b7f5;color:#fff;border-radius:10px;text-decoration:none;font-size:18px">点这里唤起手机 QQ 登录</a>'.format(html.escape(link))
            hint = "二维码生成于 {} 秒前，有效期约 2 分钟，页面每 15 秒自动换新。".format(age)
        else:
            main_html = "<form method='post' action='/{}/restart' style='margin:14px 0'><button type='submit' style='padding:14px 26px;background:#ff8f3c;color:#fff;border:none;border-radius:10px;font-size:18px'>&#128640; 二维码已停更（{}秒）— 点这里重启登录流程</button></form>".format(TOKEN, age)
            hint = "当前码已过期且 NapCat 不再产出新链接。点上方按钮重启 NapCat，或什么都不做等 15 秒自动刷新。" if not fresh else "暂无登录链接，等待 NapCat 生成中..."
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta http-equiv='refresh' content='15'>"
            "<title>肥鱼取码</title>"
            "<body style='font-family:sans-serif;text-align:center;padding-top:20px'>"
            "<h2>&#128308; 离线，等待登录</h2>{}{}<p style='color:#666;font-size:14px'>{}</p>"
            "<p><a href='' style='color:#12b7f5'>⟳ 手动刷新本页</a></p>"
            "</body>"
        ).format(qr_html, main_html, hint)
        self._send(200, body.encode("utf-8"))


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
