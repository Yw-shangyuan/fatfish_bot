#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None

CONTAINER = "snowluma"
OPS_DIR = Path("/home/ubuntu/ops")
LOG_PATH = OPS_DIR / "recovery.log"
LOCK_PATH = OPS_DIR / ".recover-snowluma.lock"
STATE_PATH = OPS_DIR / ".recovery-state.json"
MUTE_PATH = Path("/home/ubuntu/.config/fatfish-sentinel/mute")
ONEBOT_CONFIG = Path("/srv/snowluma/data/config/onebot.json")
REQUIRED_FAILURES = 3
COOLDOWN_SECONDS = 3600
POST_RESTART_TIMEOUT = 180


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_command(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def append_log(event: str, **fields: Any) -> None:
    record = {"ts": now_iso(), "event": event, **fields}
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fail_count": 0, "last_attempt": 0}


def save_state(state: dict[str, Any]) -> None:
    atomic_write_json(STATE_PATH, state)


@dataclass
class HealthSnapshot:
    container_running: bool
    qq_pids: list[int]
    ws_connections: int
    login_ok: bool | None
    login_detail: str = ""
    hook_unavailable: bool = False

    @property
    def duplicate_qq(self) -> bool:
        return len(self.qq_pids) > 1

    @property
    def healthy(self) -> bool:
        return (
            self.container_running
            and len(self.qq_pids) == 1
            and self.ws_connections > 0
            and self.login_ok is True
        )

    def recoverable_reason(self) -> str:
        if not self.container_running or self.ws_connections > 0:
            return ""
        reasons = []
        if self.duplicate_qq:
            reasons.append("duplicate_qq")
        if self.login_ok is True:
            if self.hook_unavailable:
                reasons.append("qqhook_unavailable")
            reasons.append("login_ok_ws_down")
        return ",".join(reasons)

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["duplicate_qq"] = self.duplicate_qq
        value["healthy"] = self.healthy
        value["recoverable_reason"] = self.recoverable_reason()
        return value


def _container_running() -> bool:
    try:
        result = run_command(["docker", "ps", "--format", "{{.Names}}", "--filter", "name=^snowluma$"])
        return result.returncode == 0 and CONTAINER in result.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return False


def _qq_main_pids() -> list[int]:
    result = run_command(["docker", "exec", CONTAINER, "ps", "-eo", "pid=,args="], timeout=20)
    if result.returncode != 0:
        return []
    pids = []
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not match:
            continue
        args = match.group(2).strip()
        if "--type=" in args or "chrome_crashpad_handler" in args or "/proc/self/exe" in args:
            continue
        if re.match(r"^(?:/opt/QQ/qq|qq)(?:\s|$)", args) and (
            "--relaunch" in args or "--no-sandbox" in args
        ):
            pids.append(int(match.group(1)))
    return pids


def _ws_connections() -> int:
    result = run_command(["ss", "-tn", "state", "established"])
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if ":6199" in line)


def _login_status() -> tuple[bool, str]:
    token = ""
    try:
        config = json.loads(ONEBOT_CONFIG.read_text(encoding="utf-8"))
        servers = config.get("networks", {}).get("httpServers") or [{}]
        token = servers[0].get("accessToken", "") or ""
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "http://127.0.0.1:3000/get_login_info",
        data=b"{}",
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("retcode") == 0:
            return True, "retcode=0"
        return False, f"retcode={payload.get('retcode')}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _hook_unavailable() -> bool:
    try:
        result = run_command(["docker", "logs", "--since", "15m", CONTAINER], timeout=20)
        text = result.stdout + result.stderr
        return "Client private-message reporting is unavailable" in text
    except (OSError, subprocess.SubprocessError):
        return False


def snapshot() -> HealthSnapshot:
    running = _container_running()
    if not running:
        return HealthSnapshot(False, [], 0, None, "container_not_running")
    pids = _qq_main_pids()
    ws = _ws_connections()
    login_ok, login_detail = _login_status()
    return HealthSnapshot(
        container_running=True,
        qq_pids=pids,
        ws_connections=ws,
        login_ok=login_ok,
        login_detail=login_detail,
        hook_unavailable=_hook_unavailable(),
    )


def _restart_container() -> tuple[bool, str]:
    try:
        result = run_command(["docker", "restart", CONTAINER], timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "docker restart failed")[:500]
    return True, "docker restart completed"


def _finish(
    *,
    attempted: bool,
    success: bool,
    reason: str,
    source: str,
    detail: str,
    before: HealthSnapshot | None,
    after: HealthSnapshot | None,
) -> dict[str, Any]:
    result = {
        "attempted": attempted,
        "success": success,
        "reason": reason,
        "source": source,
        "detail": detail,
        "before": before.public_dict() if before else None,
        "after": after.public_dict() if after else None,
    }
    append_log("recovery_result", **result)
    return result


def _try_lock(handle) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    import msvcrt

    handle.seek(0)
    handle.write("0")
    handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def recover(reason: str, source: str = "manual") -> dict[str, Any]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        if not _try_lock(lock):
            return _finish(
                attempted=False,
                success=False,
                reason=reason,
                source=source,
                detail="another recovery is already running",
                before=None,
                after=None,
            )

        before = snapshot()
        if before.healthy:
            return _finish(
                attempted=False,
                success=True,
                reason=reason,
                source=source,
                detail="service is already healthy",
                before=before,
                after=before,
            )
        recoverable = before.recoverable_reason()
        if not recoverable:
            return _finish(
                attempted=False,
                success=False,
                reason=reason,
                source=source,
                detail="state is not safely recoverable automatically",
                before=before,
                after=None,
            )

        append_log(
            "recovery_start",
            reason=reason or recoverable,
            source=source,
            before=before.public_dict(),
        )
        restarted, detail = _restart_container()
        state = load_state()
        state["last_attempt"] = time.time()
        state["fail_count"] = 0
        save_state(state)
        if not restarted:
            return _finish(
                attempted=True,
                success=False,
                reason=reason,
                source=source,
                detail=detail,
                before=before,
                after=None,
            )

        last = before
        deadline = time.monotonic() + POST_RESTART_TIMEOUT
        while True:
            time.sleep(5)
            try:
                last = snapshot()
                if last.healthy:
                    return _finish(
                        attempted=True,
                        success=True,
                        reason=reason,
                        source=source,
                        detail="snowluma recovered",
                        before=before,
                        after=last,
                    )
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                break
        return _finish(
            attempted=True,
            success=False,
            reason=reason,
            source=source,
            detail=f"recovery verification timed out: {detail}",
            before=before,
            after=last,
        )


def maybe_auto_recover(now: float | None = None) -> dict[str, Any] | None:
    if MUTE_PATH.exists():
        return None
    current_time = time.time() if now is None else now
    state = load_state()
    current = snapshot()
    if current.ws_connections > 0:
        if state.get("fail_count"):
            state["fail_count"] = 0
            save_state(state)
        return None

    reason = current.recoverable_reason()
    if not reason:
        if state.get("fail_count"):
            state["fail_count"] = 0
            save_state(state)
        return None

    state["fail_count"] = int(state.get("fail_count", 0)) + 1
    if state["fail_count"] < REQUIRED_FAILURES:
        save_state(state)
        return None
    last_attempt = float(state.get("last_attempt", 0))
    if last_attempt and current_time - last_attempt < COOLDOWN_SECONDS:
        save_state(state)
        append_log(
            "recovery_cooldown",
            reason=reason,
            fail_count=state["fail_count"],
            last_attempt=state.get("last_attempt", 0),
        )
        return None

    result = recover(reason=reason, source="sentinel")
    if result["attempted"]:
        state["last_attempt"] = current_time
        state["fail_count"] = 0
    save_state(state)
    return result if result["attempted"] else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or recover the snowluma QQ adapter.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--reason", default="manual")
    args = parser.parse_args()
    if args.restart:
        result = recover(reason=args.reason, source="manual")
    else:
        result = snapshot().public_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not args.restart or result.get("success") else 1)


if __name__ == "__main__":
    main()
