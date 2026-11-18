#!/usr/bin/env bash
# 延迟重启 AstrBot：先让当前回复发出去，再杀进程让 systemd 拉起
set -u
sleep 10
pid=$(pgrep -f "AstrBot/.venv/bin/python main.py" | head -1)
if [ -n "${pid}" ]; then
  kill "${pid}"
  echo "$(date '+%F %T') killed astrbot pid=${pid}" >> /home/ubuntu/ops/restart.log
fi
