# 仓库与远程拓扑（Push Topology）

本机共有 **2 个本地 git 仓库、4 个推送目标**。推送一律按本表执行，不要凭记忆操作。

## 1. 本地仓库与远程名

| # | 本地路径 | 远程名 | SSH 地址 | 实际目标 | 内容 |
|:--|:--|:--|:--|:--|:--|
| 1 | /home/ubuntu/AstrBot | github | git@github.com:Yw-shangyuan/fish-astrbot.git | GitHub · fish-astrbot | AstrBot 主程序 fork：core、内置 star、配置 schema |
| 2 | /home/ubuntu/AstrBot | gitee | git@gitee-backup:YwShangyuan/fish-astrbot.git | Gitee · fish-astrbot | 同上（镜像） |
| 3 | /home/ubuntu/bot-src | origin | git@github.com:Yw-shangyuan/fatfish_bot.git | GitHub · fatfish_bot | 源码快照：plugins + ops + persona（脱敏） |
| 4 | /home/ubuntu/bot-src | gitee | git@gitee-backup:YwShangyuan/fish-ops.git | Gitee · fish-ops | 同上（镜像） |

两仓的 main 是两条互不相关的历史，各自推各自的双远程，禁止跨仓互推。

## 2. 改了什么就该推哪里

- **改了 /home/ubuntu/AstrBot/astrbot/\*\*** → 提交并推送 #1 与 #2：
  ```bash
  git -C /home/ubuntu/AstrBot add -A
  git -C /home/ubuntu/AstrBot commit -m "..."
  git -C /home/ubuntu/AstrBot push github main
  git -C /home/ubuntu/AstrBot push gitee main
  ```
  注意：该仓 .gitignore 含 data/，插件源码与运行数据**不在**这个仓里。

- **改了插件源码（/home/ubuntu/AstrBot/data/plugins/\*\*）或运维目录（/home/ubuntu/ops/\*\*）** → 只跑一条命令，它会同步、脱敏、重建 VERSIONS.txt 并推 #3 与 #4：
  ```bash
  bash /home/ubuntu/bot-src/ops/backup-src.sh
  ```
  它做 4 件事：rsync data/plugins → bot-src/plugins（排除 .git、__pycache__、*.pyc、**\*.bak\***、assets、日志）；rsync /home/ubuntu/ops → bot-src/ops（同样 \*delete，见第 3 节）；跑 tools/persona_export.py 导出脱敏 persona；重写 VERSIONS.txt 后 commit 并推送 gitee、github（github 带 3 次重试）。
  cron 每 3 天自动执行一次，手工执行随时可以。

- **两边都改了** → 先提交推送 #1#2，再跑 backup-src.sh。这样 VERSIONS.txt 里的 astrbot_snapshot_commit 记录的才是新哈希。

## 3. 三个不要

- **不要直接向插件目录推送。** /home/ubuntu/AstrBot/data/plugins/astrbot_plugin_bilibili_ai_bot 内嵌着上游仓库，origin=https://github.com/chenluQwQ/astrbot_plugin_bilibili_ai_bot.git，那是原作者的仓库。插件改动一律经 bot-src 快照走 #3#4。
- **不要在 bot-src/ops 或 bot-src/plugins 里直接写文件。** backup-src.sh 对这些目录做 `rsync --delete`，源分别是 /home/ubuntu/ops 与 /home/ubuntu/AstrBot/data/plugins；写在快照仓里的内容下次同步就被删。要加文档请写进 /home/ubuntu/ops/docs/。
- **不要把凭据或运行数据推进任何仓。** data/ 已被主仓忽略；persona/plugin_configs/\*.json 由 tools/persona_export.py 脱敏后导出（secret 字段留空）；真实 cookie 只存在于 /home/ubuntu/AstrBot/data/config/。

## 4. 校验四个目标

```bash
git -C /home/ubuntu/AstrBot ls-remote --heads github main
git -C /home/ubuntu/AstrBot ls-remote --heads gitee  main
git -C /home/ubuntu/bot-src     ls-remote --heads origin main
git -C /home/ubuntu/bot-src     ls-remote --heads gitee  main
```
四条返回的哈希应分别等于两个本地仓的 HEAD。

## 5. 平台标签与真实实现（勿凭标签推断）

| 平台 id | 适配器 type | 真实协议端 |
|:--|:--|:--|
| napcat-qq | aiocqhttp（OneBot v11） | SnowLuma，容器 motricseven7/snowluma:latest |

id 里的 napcat 是历史标签（NapCat 会顶号，已弃用）。改 id 会让所有 napcat-qq:FriendMessage:* 白名单条目与 conversations 历史 key 失配，故保持不改，只在此登记事实。
