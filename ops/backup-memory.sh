#!/usr/bin/env bash
# FatFish online memory backup: consistent staging snapshot -> age encryption -> GitHub.
# This entry never stops or restarts QQ, SnowLuma, AstrBot, or message channels.
set -euo pipefail

DST=/home/ubuntu/backups/data
PUB=$(cat /home/ubuntu/.ssh/fatfish_age_pub.txt)
REPO=/home/ubuntu/bot-src
SNAPSHOTTER=/home/ubuntu/ops/backup_memory.py
STAMP=$(date +%Y%m%d-%H%M%S)
T0=$(date +%s)
RAW=$DST/fatfish-memory-$STAMP.tar.gz
STAGE=
WT=
OK=0
SENDKEY=$(grep -s '^SENDKEY=' /home/ubuntu/.config/fatfish-sentinel/env | cut -d= -f2- || true)

notify() {
  [ -z "${SENDKEY:-}" ] && return 0
  curl -s -m 10 "https://sctapi.ftqq.com/${SENDKEY}.send" \
    --data-urlencode "title=肥鱼记忆备份" \
    --data-urlencode "desp=$1" >/dev/null 2>&1 || true
}

cleanup() {
  local status=$?
  [ -n "$STAGE" ] && rm -rf -- "$STAGE"
  rm -f -- "$RAW"
  if [ -n "$WT" ] && [ -d "$WT" ]; then
    git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || rm -rf -- "$WT"
  fi
  if [ "$OK" != "1" ]; then
    notify "❌ 在线记忆备份失败(exit=$status)。QQ、SnowLuma、AstrBot 和消息通道未被停止。详情看 /home/ubuntu/backups/backup-memory.log"
  fi
}
trap cleanup EXIT

mkdir -p "$DST"
STAGE=$(mktemp -d "/home/ubuntu/backups/memory-staging-$STAMP.XXXXXX")

python3 "$SNAPSHOTTER" --destination "$STAGE"
tar -I "gzip -1" -cf "$RAW" -C "$STAGE" .
rm -rf -- "$STAGE"
STAGE=

age -r "$PUB" -o "$RAW.age" "$RAW"
rm -f -- "$RAW"
sha256sum "$RAW.age" > "$RAW.age.sha256"

ls -t "$DST"/fatfish-memory-*.age 2>/dev/null | tail -n +8 | xargs -r rm -f || true
ls -t "$DST"/fatfish-memory-*.age.sha256 2>/dev/null | tail -n +8 | xargs -r rm -f || true

BR=memory-$STAMP
WT=/tmp/fatfish-memory-$STAMP
cd "$REPO"
git fetch -q --prune origin
git worktree add --orphan -q -b "$BR" "$WT"

BASE=$(basename "$RAW.age")
SIZE=$(stat -c%s "$RAW.age")
cp "$RAW.age.sha256" "$WT/"
{
  echo "# FatFish online memory backup $STAMP"
  echo "Scope: AstrBot memory/configuration and static SnowLuma configuration."
  echo "Excluded: NapCat, QQ runtime/login state, VNC credentials, logs, caches, plugin sources and workspaces."
  echo "Consistency: per-file online snapshot; SQLite uses the online backup API."
  echo "Decrypt: age -d -i fatfish_age_identity.txt $BASE > $BASE"
  echo "Restore: inspect the archive first, then restore selected paths after stopping their writers."
  echo "If split into part files: cat *.part-* > $BASE before decryption."
  echo "sha256: verify the decrypted tar.gz with $BASE.sha256."
} > "$WT/RESTORE-README.txt"

FILES=(RESTORE-README.txt "$BASE.sha256")
if [ "$SIZE" -le 95000000 ]; then
  cp "$RAW.age" "$WT/$BASE"
  FILES+=("$BASE")
else
  split -b 90m "$RAW.age" "$WT/$BASE.part-"
  FILES+=("$BASE".part-*)
fi
git -C "$WT" add -- "${FILES[@]}"
git -C "$WT" commit -qm "memory backup $STAMP ($(du -h "$RAW.age" | cut -f1) encrypted)"
git push -q origin "$BR"
git worktree remove --force "$WT"
WT=

git ls-remote --heads origin "refs/heads/$BR" | grep -q . || {
  echo "ERROR: new memory backup branch not visible on remote; pruning skipped"
  exit 1
}

DELS=""
DELFAIL=""
BKLIST=$(git ls-remote --heads origin "refs/heads/memory-*" | awk '{print $2}' | sed 's|refs/heads/||' | sort)
BK_CNT=$(printf '%s\n' "$BKLIST" | grep -c . || true)
if [ "${BK_CNT:-0}" -gt 3 ]; then
  DEMLIST=$(printf '%s\n' "$BKLIST" | grep -vx "$BR" | head -n -2 || true)
  for b in $DEMLIST; do
    [ -z "$b" ] && continue
    if git push -q origin --delete "$b"; then
      git branch -D "$b" >/dev/null 2>&1 || true
      DELS="$DELS $b"
    else
      DELFAIL="$DELFAIL $b"
    fi
  done
fi

OK=1
MINS=$(( ($(date +%s) - T0) / 60 ))
notify "✅ 在线记忆备份完成：$(du -h "$RAW.age" | cut -f1) 加密包已推送到 GitHub 分支 $BR。QQ 与消息通道全程未停止。全程${MINS}分钟。🧹 本次删除:${DELS:- 无}${DELFAIL:+ ｜⚠️删除失败:${DELFAIL}}"
exit 0
