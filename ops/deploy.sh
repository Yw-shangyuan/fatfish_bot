#!/bin/bash
set -uo pipefail
cd /home/ubuntu
echo "[1/4] 校验迁移包"
gzip -t astrbot-migrate-slim.tar.gz 2>/dev/null || { echo "!! 迁移包还没传完或损坏，等文件到 46M 再跑一次"; exit 1; }
echo "[2/4] 解压数据+代码"
rm -rf AstrBot
tar -xzf astrbot-migrate-slim.tar.gz
echo "[3/4] 挂接已装好的依赖环境 + 注册开机自启"
ln -sfn /home/ubuntu/AstrBotCode/.venv /home/ubuntu/AstrBot/.venv
sudo tee /etc/systemd/system/astrbot.service > /dev/null <<'UNIT'
[Unit]
Description=AstrBot
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AstrBot
ExecStart=/home/ubuntu/AstrBot/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now astrbot
echo "[4/4] 等服务起来，看状态："
sleep 12
systemctl is-active astrbot || true
sudo journalctl -u astrbot -n 12 --no-pager | tail -12
echo DEPLOY_DONE
