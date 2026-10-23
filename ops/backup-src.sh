#!/usr/bin/env bash
# One-command source backup: plugins + ops -> bot-src repo -> GitHub
set -e
SRC=/home/ubuntu/AstrBot/data/plugins
DST=/home/ubuntu/bot-src
rsync -a --delete --exclude .git --exclude __pycache__ --exclude "*.pyc" "$SRC/" "$DST/plugins/"
for f in deploy.sh grab.py sentinel.py backup-src.sh; do [ -f "/home/ubuntu/$f" ] && cp -f "/home/ubuntu/$f" "$DST/ops/" || true; done
cp -f /etc/systemd/system/astrbot.service "$DST/ops/" 2>/dev/null || true
cd "$DST"
git add -A
if git diff --cached --quiet; then echo "no changes, nothing to push"; exit 0; fi
git commit -qm "chore: source backup $(date -u +%FT%TZ)"
git push -q origin main
echo "pushed: $(git rev-parse --short HEAD) -> fatfish_bot main"
