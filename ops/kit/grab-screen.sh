#!/usr/bin/env bash
# SnowLuma login-QR grabber: click virtual "refresh", screenshot, crop,
# print mtime line then base64 of the png (single-ssh transport, no scp).
PY=/home/ubuntu/AstrBot/.venv/bin/python
timeout 8 "$PY" /home/ubuntu/ops/vnc_click.py 639 394 >/dev/null 2>&1 || true
sleep 3
docker exec snowluma ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :1 -frames:v 1 /tmp/s.png || { echo "ERR: screenshot failed"; exit 1; }
docker exec snowluma ffmpeg -y -loglevel error -i /tmp/s.png -vf crop=340:340:470:192,scale=680:680 /tmp/q.png
docker cp snowluma:/tmp/q.png /tmp/fish_qr.png
stat -c %y /tmp/fish_qr.png | cut -c1-19
base64 /tmp/fish_qr.png