# FatFish User Context

按 QQ 私聊用户加载独立的基本介绍、长期记忆和知识库引用。插件提供分信任等级的长期记忆整理，不执行 Git 提交或推送。

## 数据目录

默认位置：`/home/ubuntu/AstrBot/data/fatfish_user_context`

```text
core.md
owner_guidance.md
bindings.json
users/<user_hash>/intro.md
users/<user_hash>/memory.md
users/<user_hash>/pending.jsonl
users/<user_hash>/memory_state.json
users/<user_hash>/backups/
backups/persona/
backups/owner_guidance/
```

`user_hash = SHA256("qq:" + QQ号)`。QQ 号只在计算和命令参数中使用，不写入用户文件或导出清单。

`core.md` 是主人格的唯一人工编辑源。插件加载完成或执行 `/qq人格重载` 时，会将该文件同步到 `persona_id` 指定的 AstrBot 人格。同步前会在 `backups/persona` 保存旧版本。所有使用该人格的会话都会受到影响。

## 知识库命令

以下命令仅 QQ 私聊中的 AstrBot 管理员可用：

```text
/qq知识库列表 [页码]
/qq知识库 <QQ号>
/qq知识库 <QQ号> + <知识库id>
/qq知识库 <QQ号> - <知识库id>
```

- 添加不存在的知识库 ID 会被拒绝。
- 添加引用时，如果用户尚未绑定，会自动创建绑定和空 `memory.md`。
- 删除引用只修改 `bindings.json`，不删除知识库或其文档。
- 最后一个引用删除后保留 `kb_ids: []`，表示明确不使用知识库。
- 未绑定用户保持 AstrBot 原有默认行为。插件首次接管绑定时会保存原会话配置；之后如果从 `bindings.json` 删除该用户绑定，会恢复接管前的配置。
- 已绑定用户在等待 LLM 请求时重新应用配置，下一条私聊消息生效。
- 会话配置读写异常时会停止本次 LLM 请求，避免继续使用旧的个性化知识库。

## 用户文件

`intro.md` 可以不存在。`memory.md` 可以为空。已存在的文件必须包含以下文件头：

```markdown
---
schema_version: 1
user_hash: <64位小写SHA-256>
updated_at: <ISO 8601时间>
---
```

加载时，当前 QQ 哈希、绑定键、目录名和文件头必须一致。哈希不匹配时，用户资料不会注入，该用户的个性化知识库会被关闭。

手动编辑记忆时可保留文件头并修改正文。程序更新应调用 `UserContextStore.update_memory()`，该方法会原子替换文件并刷新时间。

## 长期记忆

仅 `owner_qq` 指定的主人可以管理记忆和写入 `owner_guidance.md`。其他用户的内容只形成该用户的事实、偏好和事件记录，不能修改主人格、主人指导或权限规则。

短期对话在发送完成后写入 `pending.jsonl`，该文件不会注入提示词。每日 `daily_summary_time`（默认 03:30）按用户调用当前 LLM Provider 整理进 `memory.md`；主人的明确教导可整理进 `owner_guidance.md`。总结失败不会删除临时记录，也不会覆盖旧长期记忆。

成功处理的短期记录默认保留 7 天，之后自动清理。未处理或处理失败的记录不会因到期而删除。每日任务与手动整理使用用户级异步锁，长期记忆覆盖前会保存历史版本。

### 记忆管理命令

以下命令仅主人在 QQ 私聊中可用：

```text
/qq记忆启用 <QQ号>
/qq记忆整理 <QQ号>
/qq记忆追加 <QQ号> <内容>
/qq记忆教导 <内容>
/qq记忆状态 <QQ号>
/qq记忆导出 <QQ号>
```

- `记忆启用`：创建绑定、空长期记忆和短期队列，不配置知识库引用。
- `记忆整理`：立即总结该用户的未处理短期记录。
- `记忆追加`：直接向该用户长期记忆追加一条带时间的记录。
- `记忆教导`：直接追加主人长期指导，所有 QQ 私聊共享。
- `记忆状态`：查看待处理数量、长期记忆大小和最近清理结果。

非流式发送完成后由 `after_message_sent` 记录真实回复。若平台使用流式发送且未触发该钩子，这部分回复不会进入短期队列，应以运行日志和实际消息验证。

## 导出

管理员命令：

```text
/qq记忆导出 <QQ号>
```

或服务器命令：

```bash
python3 /home/ubuntu/AstrBot/data/plugins/astrbot_plugin_fatfish_user_context/export.py \
  --data-dir /home/ubuntu/AstrBot/data/fatfish_user_context \
  --qq <QQ号> \
  --output-dir /home/ubuntu/exports/fatfish_user_context
```

导出包含介绍、记忆和不含原始 QQ 号的 `manifest.json`。代码不会主动向文件写入原始 QQ 号；如果人工在介绍或记忆正文中写入了 QQ 号，导出会按原文保留。导出目录不在 Git 仓库中，不会自动推送。

## 启用

首次安装后，通过 WebUI 重载插件，或安排 AstrBot 重启。未加载插件前，新增文件不会改变线上行为。

运行独立自测：

```bash
cd /home/ubuntu/AstrBot/data/plugins/astrbot_plugin_fatfish_user_context
python3 -B selftest.py
python3 -B -m unittest -v test_memory.py
```
