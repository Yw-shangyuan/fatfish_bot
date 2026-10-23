#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""肥鱼哨兵：定时体检，异常经 Server酱 推送到微信。

检查项：
  - napcat 容器在跑（docker ps）
  - astrbot 服务 active（systemctl）
  - QQ 登录态有效（本地 NapCat get_login_info，retcode==0；不产生任何QQ流量）
  - NapCat<->AstrBot 反向 ws 链路（:6199 ESTAB 数 >= 1）

行为：
  - 首检有异常 -> 等20秒全量复检，以复检结果为准（防重启窗口/瞬时抖动误报）
  - 状态 正常->异常：立即推送；持续异常每 2 小时重复提醒一次（带次数）
  - 状态 异常->正常：推送恢复通知（含离线时长）
  - 维护静音：touch /home/ubuntu/.config/fatfish-sentinel/mute 后只记状态不推送
    （计划内重启 astrbot/napcat 前先 touch，完事删掉）

用法:
  sentinel.py          # cron 例行体检
  sentinel.py --test   # 发一条测试推送（需先配置 SENDKEY）

SENDKEY 位于 /home/ubuntu/.config/fatfish-sentinel/env（SENDKEY=xxx），
故意放在 ops 目录之外，避免随 backup-src.sh 同步进 git。
"""
import json
import os
import subprocess
import sys
import time
from urllib import parse as urlparse
from urllib import request as urlreq

BASE = "/home/ubuntu/.config/fatfish-sentinel"
ENVF = os.path.join(BASE, "env")
STATEF = os.path.join(BASE, "state.json")
MUTE = os.path.join(BASE, "mute")
REPEAT_SEC = 2 * 3600   # 同一故障持续中的重复提醒间隔
RECHECK_WAIT = 20       # 首检失败后的复测等待秒数


def sh(cmd):
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)


def load_key():
    """读取 Server酱 SendKey，未配置返回空串。"""
    if not os.path.exists(ENVF):
        return ""
    for line in open(ENVF, encoding="utf-8"):
        if line.strip().startswith("SENDKEY="):
            return line.strip().split("=", 1)[1]
    return ""


def push(key, title, desp):
    """调用 Server酱 API 推送。返回是否成功。"""
    if not key:
        print("[sentinel] SENDKEY 未配置（%s），跳过推送。" % ENVF)
        return False
    url = "https://sctapi.ftqq.com/%s.send" % key
    data = urlparse.urlencode({"title": title[:32], "desp": desp}).encode()
    req = urlreq.Request(url, data=data, headers={"User-Agent": "fatfish-sentinel"})
    try:
        with urlreq.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
        ok = '"code":0' in body
        print("[sentinel] push %s: %s" % ("ok" if ok else "fail", body[:150]))
        return ok
    except Exception as e:  # 网络问题不能让哨兵整体崩掉
        print("[sentinel] push error: %s" % e)
        return False


def checks():
    """执行全部体检。返回 {项目名: (是否健康, 详情文本)}。"""
    out = {}
    nap_ok = "ok" in sh("docker ps --format '{{.Names}}' | grep -qx napcat && echo ok").stdout
    out["napcat容器"] = (nap_ok, "" if nap_ok else "容器未运行")

    r = sh("systemctl is-active astrbot")
    st = (r.stdout or "").strip()
    out["AstrBot服务"] = (st == "active", "" if st == "active" else "状态=%s" % st)

    # QQ 登录态：容器在跑才有意义，否则归因到容器项，避免重复报警
    if nap_ok:
        r = sh("curl -s -m 8 -X POST http://127.0.0.1:3000/get_login_info "
               "-H 'Content-Type: application/json' -d '{}'")
        try:
            d = json.loads(r.stdout)
            ok = d.get("retcode") == 0
            det = "" if ok else "retcode=%s" % d.get("retcode")
            if not ok:
                tail = sh("docker logs --since 30m napcat 2>&1 "
                          "| grep -E 'KickedOffLine|下线通知|二维码已保存' | tail -2")
                det += "\n" + (tail.stdout or "").strip()[:300]
        except Exception:
            ok, det = False, "NapCat 3000 接口无响应"
        out["QQ登录态"] = (ok, det)
    else:
        out["QQ登录态"] = (True, "")  # 容器挂了时抑制本项，防止一次故障两条报警

    r = sh("ss -tn 2>/dev/null | grep ':6199' | grep -c ESTAB")
    try:
        n = int((r.stdout or "0").strip())
    except ValueError:
        n = 0
    out["ws链路6199"] = (n >= 1, "ESTAB=%d" % n)
    return out


def main():
    if "--test" in sys.argv:
        push(load_key(), "🐳 哨兵测试", "肥鱼哨兵已就位，这条是测试推送，咕噜~")
        return

    key = load_key()
    state = {}
    if os.path.exists(STATEF):
        try:
            state = json.load(open(STATEF, encoding="utf-8"))
        except Exception:
            state = {}

    res = checks()
    if any(not ok for ok, _ in res.values()):
        time.sleep(RECHECK_WAIT)
        res = checks()  # 以复检为准

    now = time.time()
    msgs = []
    for item, (ok, det) in res.items():
        st = state.get(item) or {"status": "up", "since": now, "last_alert": 0, "alert_n": 0}
        new = "up" if ok else "down"
        if new != st.get("status"):
            if new == "down":
                st.update(status="down", since=now, last_alert=now, alert_n=1)
                msgs.append("🔴 %s 异常\n%s" % (item, det or "无详情"))
            else:
                mins = int((now - st.get("since", now)) / 60)
                msgs.append("✅ %s 已恢复（离线 %d 分钟）" % (item, mins))
                st.update(status="up", last_alert=0, alert_n=0)
        elif new == "down" and now - st.get("last_alert", 0) > REPEAT_SEC:
            st["last_alert"] = now
            st["alert_n"] = st.get("alert_n", 1) + 1
            msgs.append("⏰ %s 仍异常（第 %d 次提醒）\n%s" % (item, st["alert_n"], det))
        state[item] = st
    json.dump(state, open(STATEF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if msgs and not os.path.exists(MUTE):
        bad = sum(1 for v in res.values() if not v[0])
        title = "🔴 肥鱼哨兵：%d 项异常" % bad if bad else "✅ 肥鱼哨兵：已恢复"
        push(key, title, "\n\n---\n\n".join(msgs))
        print("[sentinel] alerts sent: %d" % len(msgs))


main()
