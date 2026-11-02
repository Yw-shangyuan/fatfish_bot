# 鱼箱（fishbox）交接文档

更新时间：2026-11-02 14:45 CST
用途：把当前状态、待改项、坑点交接给下一个 agent 或人工接手。

---

## 1. 一句话现状

沙箱在跑、能调工具；桥接插件已加载运行（14:30 重启后 PID 691975），多卡组合并转发已真机验证通过。

---

## 2. 目录与文件

| 路径 | 说明 |
| --- | --- |
| /home/ubuntu/fishbox/ | 沙箱主体（executor.py、server.py、client.py、tools/、cache/、run_server.sh、server.log） |
| /home/ubuntu/fishbox/fishbox.sock | unix socket，权限 0600，bot 侧唯一入口 |
| /home/ubuntu/fishbox/tools/<name>/ | 工具目录：manifest.json + main.py + selftest.py |
| /home/ubuntu/fishbox/cache/<name>/ | 工具唯一可写目录（卡库缓存在这里） |
| /home/ubuntu/AstrBot/data/plugins/astrbot_plugin_fishbox/ | 桥接插件（main.py、metadata.yaml） |
| /home/ubuntu/AstrBot/data/logs/astrbot.log | AstrBot 主日志 |
| /home/ubuntu/fishbox/server.log | 沙箱启动日志 |

---

## 3. 已完成

### 3.1 沙箱层
- executor.py：子进程执行，清空环境变量（只留 PATH、FISHBOX_*），cwd 锁在工具目录，RLIMIT 限 CPU/内存 512M/单文件 16M/句柄 64，stdout 截断，超时按 manifest。
- server.py：unix socket 薄接口，`action=list|run`，工具名严格白名单（不在 tools 目录直接拒绝）。
- client.py：只依赖标准库，`client.tools()` / `client.run(name, args)`。
- 自启：crontab 已有两条（勿重复添加）
  - `@reboot sleep 20; flock -n /tmp/fishbox.lock /home/ubuntu/fishbox/run_server.sh`
  - `* * * * * flock -n /tmp/fishbox.lock /home/ubuntu/fishbox/run_server.sh`
- 运行中的进程：`/usr/bin/python3 server.py`（cwd=/home/ubuntu/fishbox）。**必须用这个解释器启动**，`run_server.sh` 用 pgrep 匹配 `python3 server.py`，换成 venv 解释器会被误判成没跑，导致重复启动。

### 3.2 现有工具
- `echo`：回声，验证链路用。
- `hearthstone_deck`：炉石卡组码解码。
  - 数据：首次运行从 `https://api.hearthstonejson.com/v1/latest/zhCN/cards.json` 拉约 10MB，落到 `cache/hearthstone_deck/cards_zhcn.json`，之后离线。
  - 算法：base64 → varint → 跳过 3 字节头 → 第二组为英雄 dbfId → 按组读卡牌 dbfId（组号即张数）→ 映射卡名/费用并排序。
  - 输入：`{"code":"AAEC..."}`；输出：`{"hero":..., "hero_class":..., "total":..., "cards":[{"cost","name","count"}]}`
  - `hero_class` 是英雄所属职业的中文名（由 `cardClass` 经 `CLASS_ZH` 映射），查不到时为空串

### 3.3 桥接插件（astrbot_plugin_fishbox 0.1.0）
- `/鱼箱列表`：列工具（仅主人或管理员）。
- `/鱼箱 <工具名> <JSON参数>`：调工具（仅主人或管理员）。
- 群内 @ 自动识码：群消息里 @ 了机器人且含卡组码 → 自动解析并回复，回复后 `stop_event()`，不再走 LLM。
- 认码规则：`(?<![A-Za-z0-9])AA[A-Za-z0-9+/]{38,220}(?![A-Za-z0-9])`，用 `finditer` 全量匹配（不是 `search` 只取第一个），同一条消息内去重，字符种类 ≥10 的判据防误判。
- 单条消息最多解析 `DECK_MAX_PER_MSG = 10` 套；超出部分不解析，末尾附「提示」节点告知剩余数量。
- 回复形式：只解出 1 套走普通文本；≥2 套或存在溢出走一条合并转发（`Nodes`/`Node`，每套一节点，节点署名取职业名、取不到退回英雄名、截断 20 字）。逐套**串行**调用沙箱，不并发（每次调用起独立进程并各自加载 10MB 卡表）。
- 限流（常量在 main.py 顶部，可调）：
  - `DECK_COOLDOWN = 60.0`：同一个码同群 60 秒只回一次
  - `DECK_GAP = 10.0`：**跨消息批次**至少 10 秒；同一条消息里的多个码属同批，不受此限
  - `DECK_HOURLY_CAP = 30`：每群每小时 30 套，**按解出的套数扣额度**（一条消息解 3 套扣 3）；额度不足时按出现顺序只放行前面几套
  - 超限回复：`当时段解析卡组打到上限，冷却时间至：HH:MM（约 N 分钟后恢复）`，提示本身 60 秒限流一次
- 已验证：语法编译通过；闸门单测（同码跳过、跨批 10 秒、满 30 套转上限、按套扣额度、冷却剩余）；`selftest.py` 输出 `selftest ok 30 节庆萨伊`；真机群聊 14:33:50 操作员发码 → 14:33:51 日志 `Prepare to send - 宇文尚元/3406408181: [ComponentType.Nodes]`，同窗口 0 报错，snowluma 正常收下内联节点。

---

## 4. 待办（按优先级）

### P0 重启加载最新插件 —— 已完成（2026-11-02 13:56、14:30 两次）
- 原始描述只写「插件 main.py 在 11:18 改过」，未指名插件，接手时容易查错对象。准确路径：`/home/ubuntu/AstrBot/data/plugins/astrbot_plugin_fishbox/main.py`，mtime `2026-11-02 11:18:59`。
- 做法：`sudo -n systemctl restart astrbot`（约 10 秒，QQ 短暂离线）。重启前先比对「插件 mtime 晚于进程启动时间」，确认确有未加载的改动再动手，避免白重启。
- 验收：日志出现 `Loading plugin astrbot_plugin_fishbox`，重启窗口内 0 traceback。

### P1 多码处理 —— 已完成（2026-11-02 部署 14:23，真机验证 14:33）
- 实现：`finditer` 全量取码 + 去重，单条消息上限 10 套，超出只报数量不解析；≥2 套走合并转发，每套一个节点。
- 与原建议的三处差异（均为业主确认口径，接手后不要自行改回）：上限是 **10** 而非 3；额度**每解一套扣 1 格**而非按消息扣；节点署名**只用职业名**，不带英雄名。
- 闸门改造要点：原 `DECK_GAP` 逐码判定会让同一条消息里第 2 套起全被吞，故改为整批一次放闸（`_deck_batch`），跨批仍要求间隔。

### P2 真隔离（需 sudo，人工执行）
- 现在只是限流，不是断网。建议二选一：
  - systemd 单元跑 server.py，加 `ProtectSystem=strict`、`PrivateNetwork=yes`、`ReadWritePaths=/home/ubuntu/fishbox/cache`
  - 或 bwrap 包一层：`bwrap --unshare-net --ro-bind /usr /usr --ro-bind /home/ubuntu/fishbox/tools ... python3 server.py`
- 注意：`hearthstone_deck` 首次下载卡库需要联网，断网前要先预热 cache。

### P3 工具编写流程
- 目前没有「AI 写工具」的入口，只能人工往 `tools/` 里放。
- 建议：新增提案工具（写草稿到 `cache/proposals/`）+ selftest 自动跑 + 人工点头后移入 `tools/`；别让模型直接写 `tools/`。

### P4 权限收敛
- 现状：群里任何人 @ 机器人就能触发解析（受 30 套/时限流）。
- 如需收紧：加群白名单，或要求「@ + 指定前缀」才触发。

### P5 可观测
- 现状：工具调用无日志，只有沙箱崩溃才看得出来。
- 建议：server.py 落一行调用日志（时间、工具、耗时、成功与否），供 sentinel.py 巡检。

---

## 5. 坑（都是踩过的）

1. **别 rm -rf /home/ubuntu/fishbox**：11:02 曾删过一次目录，旧进程还活着但 cwd 成 `(deleted)`，出现两个 server 抢 socket。重建时先 kill 旧进程。
2. crontab 里鱼箱的两条保活已在，不要重复加 `@reboot`，否则会双启。
3. `run_server.sh` 的解释器要与 cron 一致（`/usr/bin/python3`），否则 pgrep 判不出，每分鐘起一个新进程。
4. 插件里 import client 依赖 `sys.path.insert(0, /home/ubuntu/fishbox)`，路径写死在 `FISHBOX_DIR` 环境变量兜底。
5. AstrBot 命令触发只认 `/` 开头；「鱼箱列表」不带斜杠不会命中。
6. 备份脚本 backup-data.sh 备份范围**不含** `/home/ubuntu/fishbox`，需要的话自己加进 tar 列表。
7. `selftest.py` 在工具目录裸跑**必定失败**：卡表实际在 `cache/hearthstone_deck/cards_zhcn.json`，工具目录里没有，脚本会去联网重下 10MB；而且它从不打印子进程 stderr，失败只剩一句 `JSONDecodeError`。可用跑法：先把卡表软链进一个空目录，再把 `main.py` 与 `selftest.py` 拷进去执行。此坑早于本次改动存在（已用改动前的备份件 A/B 对照确认），不是回归。
8. 本文档旧版与 `接入须知.md`、`SERVER.md`、`SERVICES.md` 均称「sudo 不可用」，**与实测不符**：`sudo -n -l` 返回 `(ALL) NOPASSWD: ALL`。相关表述已统一改成「能力可用、按约定不擅自用」。
9. 当前 QQ 协议端是 **snowluma**（`motricseven7/snowluma:latest`），它作为 OneBot WS-Client 主动连 AstrBot 的 `ws://127.0.0.1:6199/ws`；`napcat` 与 `napcat-old-hostbak` 已 `Exited (137)` 六天。AstrBot 里适配器名仍显示 `napcat-qq`，只是旧标签，别据此判断在用 napcat。
10. 在 `tools/<name>/` 下执行 `py_compile` 会生成 `__pycache__`，与沙箱的只读约定不符，改完记得清掉。
11. 本次改动前的原文件都备份为同名 `*.bak-20261102`（插件与工具两处）。回滚：`cp` 回原名，插件侧需再重启 astrbot，工具侧不需要。

---

## 6. 常用命令

    # 沙箱健康
    cd /home/ubuntu/fishbox && python3 -c "import client;print(client.tools())"

    # 单次执行（不经 server）
    cd /home/ubuntu/fishbox && echo '{"code":"AAEC..."}' | python3 executor.py hearthstone_deck

    # 看沙箱进程
    ps -eo pid,etime,cmd | grep "server.py" | grep -v grep

    # 重启 AstrBot 加载插件
    sudo -n systemctl restart astrbot

    # 验证合并转发确实发出过（有输出即插件跑通）
    grep -a 'ComponentType.Nodes' /home/ubuntu/AstrBot/data/logs/astrbot.log | tail -3

    # 确认协议端到 AstrBot 的反向 WS 在线
    ss -tn state established | grep 6199
