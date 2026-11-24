#!/usr/bin/env bash
# One-command source backup: plugins + ops + persona -> GitHub (fatfish_bot) + Gitee (fish-ops)
# Cadence: every 3 days via cron; manual runs on request. Source only, no runtime data.
set -e
SRC=/home/ubuntu/AstrBot/data/plugins
DST=/home/ubuntu/bot-src
OPS=/home/ubuntu/ops

# 1. plugin sources
rsync -a --delete --exclude .git --exclude __pycache__ --exclude '*.pyc' --exclude '*.bak*' --exclude assets --exclude '*.log' "$SRC/" "$DST/plugins/"

# 2. ops mirror (tooling + docs; no runtime artifacts, no backups)
rsync -a --delete --exclude .git --exclude __pycache__ --exclude '*.pyc' --exclude '*.bak*' --exclude 'drop/' --exclude '*.log' --exclude '*.db' --exclude '*.pid' "$OPS/" "$DST/ops/"

# 3. helper scripts living in home root
for f in /home/ubuntu/deploy.sh /home/ubuntu/grab.py /home/ubuntu/backup-data.sh /home/ubuntu/backup-memory.sh /home/ubuntu/backup-src.sh /home/ubuntu/notify.sh /home/ubuntu/set_mute.py /home/ubuntu/update_prefs.py /home/ubuntu/inspect_fu.py /home/ubuntu/patch_comment.py /home/ubuntu/patch_gate.py /home/ubuntu/patch_veto.py; do
  [ -f "$f" ] && cp -f "$f" "$DST/ops/" || true
done
cp -f /etc/systemd/system/fatfish-qr.service "$DST/ops/" 2>/dev/null || true
cp -f /etc/systemd/system/astrbot.service "$DST/ops/" 2>/dev/null || true

# 4. persona assets (personas table, KB docs, masked plugin configs)
python3 "$DST/tools/persona_export.py"

# 5. version manifest
SNAP=$(git -C /home/ubuntu/AstrBot rev-parse --short HEAD 2>/dev/null || echo unknown)
cat > "$DST/VERSIONS.txt" <<EOF
# FatFish bot source snapshot
created_utc: 2026-10-22T02:37:43Z
updated_utc: $(date -u +%FT%TZ)
host: Ubuntu 24.04.4 LTS / x86_64
astrbot_runtime: v4.29.1 (from server logs; official open source, not in this repo)
astrbot_snapshot_commit: $SNAP (working tree of /home/ubuntu/AstrBot, fork baseline; upstream commit e5e21b7)
astrbot_snapshot_repo: fish-astrbot on GitHub (Yw-shangyuan) and Gitee (YwShangyuan)
qq_protocol_endpoint: motricseven7/snowluma:latest (container: snowluma)
note: platform id napcat-qq is a legacy label; adapter type = aiocqhttp
plugin: astrbot_plugin_bilibili_ai_bot
67c7161
https://github.com/chenluQwQ/astrbot_plugin_bilibili_ai_bot.git
modified_vs_upstream: 101 (file count as of 2026-10-22)
plugin: astrbot_plugin_qq_proactive
e5e21b7
https://github.com/AstrBotDevs/AstrBot.git
modified_vs_upstream: 1813 (file count as of 2026-10-22)
plugin: astrbot_plugin_fishbox
local original, no upstream
persona: exported under persona/ with credential fields masked
EOF

cd "$DST"
git add -A
if git diff --cached --quiet; then echo "no changes, nothing to push"; exit 0; fi
git commit -qm "chore: source backup $(date -u +%FT%TZ)"

# 6. dual push: gitee first, github with retries
if git push -q gitee main 2>/dev/null; then echo "pushed gitee"; else echo "WARN gitee push failed"; fi
ok=0
for i in 1 2 3; do
  if git push -q origin main 2>/dev/null; then ok=1; break; fi
  sleep 12
done
[ "$ok" = 1 ] && echo "pushed github" || echo "WARN github push failed"
echo "head: $(git rev-parse --short HEAD)"
