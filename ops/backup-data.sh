#!/usr/bin/env bash
# FatFish data backup (channel B): cold copy -> age encrypt -> GitHub orphan branch -> WeChat notify (Server酱)
# 范围=纯记忆与登录态（缓存垃圾已排除，见下方 tar --exclude）。
# 计划任务: 每3天 04:20 一次 (crontab: 20 4 */3 * *)。
set -euo pipefail

DST=/home/ubuntu/backups/data
PUB=$(cat /home/ubuntu/.ssh/fatfish_age_pub.txt)
REPO=/home/ubuntu/bot-src
STAMP=$(date +%Y%m%d-%H%M)
T0=$(date +%s)
RAW=$DST/fatfish-data-$STAMP.tar.gz
OK=0
MUTEFILE=/home/ubuntu/.config/fatfish-sentinel/mute
SENDKEY=$(grep -s '^SENDKEY=' /home/ubuntu/.config/fatfish-sentinel/env | cut -d= -f2- || true)

mkdir -p "$DST"

# 备份通知走微信（Server酱），不再发 QQ——避免给风控增加发送行为，
# 也不依赖 QQ 在线状态。仅在完成/失败时推送。
notify() {
  [ -z "${SENDKEY:-}" ] && return 0
  curl -s -m 10 "https://sctapi.ftqq.com/${SENDKEY}.send" \
    --data-urlencode "title=肥鱼备份" \
    --data-urlencode "desp=$1" >/dev/null 2>&1 || true
}

cleanup() {
  sudo systemctl start astrbot 2>/dev/null || true
  docker start napcat >/dev/null 2>&1 || true
  rm -f "$MUTEFILE"
  [ "$OK" = "1" ] || notify "❌ 备份失败(exit=$?)，服务已恢复运行。详情看 /home/ubuntu/backups/backup.log"
}
trap cleanup EXIT

# 挂哨兵免打扰牌：冷拷贝期间 NapCat 会被主动停止，属于计划内离线
mkdir -p "$(dirname "$MUTEFILE")"
touch "$MUTEFILE"

# ---- cold snapshot window ----
sudo systemctl stop astrbot
docker stop -t 5 napcat >/dev/null

# 只备"有意义的记忆"：数据库/配置/插件数据/登录态。
# 排除的都是可再生的缓存垃圾（2026-10-26 摸底占比：QQ日志471M、表情缓存154M、
# NapCat临时47M、AstrBot临时318M），丢了不心疼，重新登录/运行会自动重建。
tar -I "gzip -1" -cf "$RAW" \
  --exclude="home/ubuntu/AstrBot/data/temp" \
  --exclude="home/ubuntu/AstrBot/data/dist" \
  --exclude="home/ubuntu/AstrBot/data/dashboard.zip" \
  --exclude="*__pycache__*" \
  --exclude="*.pyc" \
  --exclude="srv/napcat/qqdata/global/nt_data/Log" \
  --exclude="srv/napcat/qqdata/global/nt_data/Emoji" \
  --exclude="srv/napcat/qqdata/NapCat/temp" \
  --exclude="srv/napcat/qqdata/Crashpad" \
  --exclude="srv/napcat/qqdata/crash_files" \
  -C / home/ubuntu/AstrBot/data srv/napcat etc/systemd/system/astrbot.service

docker start napcat >/dev/null
sudo systemctl start astrbot
# ---- snapshot window ends ----

age -r "$PUB" -o "$RAW.age" "$RAW"
rm -f "$RAW"
sha256sum "$RAW.age" > "$RAW.age.sha256"

# local rolling: keep 7
ls -t "$DST"/*.age 2>/dev/null | tail -n +8 | xargs -r rm -f || true
ls -t "$DST"/*.sha256 2>/dev/null | tail -n +8 | xargs -r rm -f || true

# ---- push to GitHub as orphan branch ----
BR=backup-$STAMP
WT=/tmp/bkwt-$STAMP
cd "$REPO"
git fetch -q --prune origin
git worktree add --orphan -q -b "$BR" "$WT"

BASE=$(basename "$RAW.age")
SIZE=$(stat -c%s "$RAW.age")
cp "$RAW.age.sha256" "$WT/"
{
  echo "# 大肥鱼数据备份 $STAMP"
  echo "解密: age -d -i fatfish_age_identity.txt $BASE.age > $BASE"
  echo "还原: tar xzf $BASE 后按内部相对路径盖回 / 原位置, 再重启 astrbot 与 napcat"
  echo "若被拆分为 part 文件: cat *.part-* | cat > $BASE 先合并再解密"
  echo "sha256 校验文件: $BASE.sha256 (对合并解密后的包校验)"
} > "$WT/RESTORE-README.txt"

if [ "$SIZE" -le 95000000 ]; then
  cp "$RAW.age" "$WT/$BASE"
else
  split -b 90m "$RAW.age" "$WT/$BASE.part-"
fi
git -C "$WT" add -A
git -C "$WT" commit -qm "data backup $STAMP ($(du -h "$RAW.age" | cut -f1) encrypted)"
git push -q origin "$BR"
git worktree remove --force "$WT"

# remote rolling: keep 3 branches
git ls-remote --heads origin "refs/heads/backup-*" | awk '{print $2}' | sed 's|refs/heads/||' | sort | head -n -3 | while read -r b; do
  git push -q origin --delete "$b" 2>/dev/null || true
done

OK=1
MINS=$(( ($(date +%s) - T0) / 60 ))
notify "✅ 备份完成：$(du -h "$RAW.age" | cut -f1) 加密包已推送到 GitHub 分支 $BR（GitHub保留最近3份，本地7份）。全程${MINS}分钟。"
exit 0
