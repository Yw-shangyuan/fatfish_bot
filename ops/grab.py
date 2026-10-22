
import asyncio, json, gzip, shutil, subprocess, urllib.request, os
import websockets
LOG = open("/home/ubuntu/grab.log", "a", buffering=1)
def log(*a): print(*a, file=LOG, flush=True)
async def main():
    while True:
        try:
            async with websockets.connect("ws://127.0.0.1:3001", ping_interval=30) as ws:
                log("WS CONNECTED")
                while True:
                    raw = await ws.recv()
                    try:
                        d = json.loads(raw)
                    except Exception:
                        continue
                    if d.get("post_type") != "message":
                        continue
                    segs = d.get("message")
                    if not isinstance(segs, list):
                        continue
                    log("MSG:", d.get("message_type"), json.dumps(segs)[:800])
                    for s in segs:
                        if isinstance(s, dict) and s.get("type") in ("file", "json"):
                            data = s.get("data") or {}
                            if s.get("type") == "json":
                                try:
                                    j = json.loads(data.get("data") or "{}")
                                    data = j.get("data", data)
                                except Exception:
                                    pass
                            name = data.get("file_name") or data.get("file") or ""
                            log("FILE EVENT:", name, data.get("file_size"),
                                d.get("self_id"), d.get("sender", {}).get("user_id"))
                            log("FILE DATA:", json.dumps(data)[:600])
                            if "astrbot" not in name.lower() and "tar" not in name.lower():
                                continue
                            url = data.get("url") or ""
                            fid = data.get("file_id") or ""
                            ok = False
                            for u in ([url] if url else []) + _api_urls(d.get("group_id"), fid):
                                if _dl(u):
                                    ok = True; break
                            if ok and _verify():
                                shutil.move("/home/ubuntu/incoming.tmp",
                                            "/home/ubuntu/astrbot-migrate-slim.tar.gz")
                                log("FILE_SAVED -> deploy")
                                subprocess.Popen(["bash", "/home/ubuntu/deploy.sh"],
                                    stdout=open("/home/ubuntu/deploy_run.log", "w"),
                                    stderr=subprocess.STDOUT)
                                return
                            else:
                                log("DOWNLOAD_OR_VERIFY_FAILED")
        except Exception as e:
            log("ws lost:", repr(e)[:120])
            await asyncio.sleep(3)
def _api_urls(gid, fid):
    out = []
    try:
        if gid:
            r = _api("get_group_file_url", {"group_id": int(gid), "file_id": str(fid)})
            u = (r.get("data") or {}).get("url")
            if u: out.append(u)
        r = _api("get_file", {"file_id": str(fid)})
        u = (r.get("data") or {}).get("url")
        if u: out.append(u)
    except Exception as e:
        log("api fail:", repr(e)[:120])
    return out
def _api(ep, pl):
    rq = urllib.request.Request("http://127.0.0.1:3000/" + ep, data=json.dumps(pl).encode(),
                                headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(rq, timeout=60).read())
def _dl(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open("/home/ubuntu/incoming.tmp", "wb") as f:
            shutil.copyfileobj(r, f, 1048576)
        log("downloaded:", os.path.getsize("/home/ubuntu/incoming.tmp"))
        return True
    except Exception as e:
        log("dl fail:", repr(e)[:140]); return False
def _verify():
    try:
        with gzip.open("/home/ubuntu/incoming.tmp", "rb") as g:
            while g.read(1 << 20): pass
        return True
    except Exception as e:
        log("verify fail:", repr(e)); return False
asyncio.run(main())
