#!/usr/bin/env python3
"""FatFish QR login portal: token-gated page serving the live NapCat login QR.

Serves at http://HOST:8765/<TOKEN> - auto-refreshes every 15s so the phone
always sees the freshest QR (NapCat regenerates qrcode.png every ~2 min).
While the account is online the page shows status only and never leaks QR.
Wrong/missing token -> bare 404. Token lives outside the repo:
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

with open(TOKEN_FILE, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()


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


def txz_link():
    s = sh("docker logs --since 30m napcat 2>&1 | grep -aoE 'https://txz.qq.com[^ ]+' | tail -1")
    s = s.decode("ascii", "ignore").strip()
    return s if s.startswith("https://txz.qq.com/") else ""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/" + TOKEN, "/" + TOKEN + "/"):
            if path != "/" + TOKEN + "/img":
                return self._send(404, b"404 Not Found", "text/plain")
        if login_ok():
            return self._send(200, "<h2>&#128994; 肥鱼在线中，无需登录</h2><p>页面每 60 秒自动刷新。</p>".encode("utf-8"))
        # offline: live QR + one-tap link
        if path == "/" + TOKEN + "/img":
            png = qr_png()
            return self._send(200, png, "image/png") if png else self._send(404, b"no qr", "text/plain")
        age = qr_age_sec()
        link = txz_link()
        fresh = 0 <= age < 110
        status = "&#128308; 离线，等待登录"
        qr_html = '<img src="/{}/img?n={}" width="260" height="260" style="border:1px solid #ccc;border-radius:8px">'.format(TOKEN, int(time.time())) if qr_png() else "<p>暂无二维码文件</p>"
        link_html = '<a href="{}" style="display:inline-block;margin:12px 0;padding:14px 26px;background:#12b7f5;color:#fff;border-radius:10px;text-decoration:none;font-size:18px">点这里唤起手机 QQ 登录</a>'.format(html.escape(link)) if link else "<p>暂未抓到登录链接，稍等页面自动刷新</p>"
        hint = ("二维码生成于 {} 秒前，有效期约 2 分钟；页面每 15 秒自动换新。".format(age) if age >= 0 else "") + ("<br><b>码接近过期？什么都别做，等页面自动刷出下一张即可。</b>" if not fresh and age >= 0 else "")
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta http-equiv='refresh' content='15'>"
            "<title>肥鱼取码</title>"
            "<body style='font-family:sans-serif;text-align:center;padding-top:20px'>"
            "<h2>{} {}</h2>{}{}<p style='color:#666;font-size:14px'>{}</p>"
            "</body>"
        ).format(status, "", qr_html, link_html, hint)
        self._send(200, body.encode("utf-8"))


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
