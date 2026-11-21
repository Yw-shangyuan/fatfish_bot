# SnowLuma recovery

## Manual check

```bash
python3 /home/ubuntu/ops/recover_snowluma.py --check
```

This is read-only. It reports the container state, QQ main process IDs, OneBot login state, WebSocket connection count, and recent QQHook reporting failures.

## Manual recovery

```bash
python3 /home/ubuntu/ops/recover_snowluma.py --restart --reason manual
```

The command refuses to restart when the current state is already healthy or is not safely recoverable. It uses a nonblocking lock to prevent concurrent restarts, runs `docker restart snowluma`, and waits up to 180 seconds for a healthy QQ process, login state, and WebSocket connection.

AstrBot is not restarted by this script.

## Automatic recovery

`/home/ubuntu/ops/sentinel.py` imports `recover_snowluma` and calls `maybe_auto_recover()` after its normal checks.

Automatic action requires:

- no established connection on port 6199;
- a recoverable state: duplicate QQ main processes, or valid login with a missing WebSocket connection/QQHook reporting failure;
- three consecutive failed checks;
- no maintenance mute file;
- no recovery attempt in the previous 3600 seconds.

A login failure without a recoverable process/Hook condition only produces alerts. The cooldown limits restart loops.

## Files

- `/home/ubuntu/ops/recovery.log`: timestamped JSON Lines recovery audit.
- `/home/ubuntu/ops/.recover-snowluma.lock`: process lock.
- `/home/ubuntu/ops/.recovery-state.json`: failure count and last attempt timestamp.
- `/home/ubuntu/ops/test_recover_snowluma.py`: mocked tests; does not restart Docker.

## Rollback

Restore the timestamped backup of `sentinel.py` to disable automatic recovery. The standalone script only runs when explicitly called, so it does not need to be removed for rollback.
