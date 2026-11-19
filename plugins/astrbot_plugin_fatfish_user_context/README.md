# FatFish User Context

按 QQ 私聊用户加载独立的基本介绍、长期记忆和知识库引用。插件不修改 AstrBot 核心源码，不启用自动学习，也不执行 Git 提交或推送。

## 数据目录

默认位置：`/home/ubuntu/AstrBot/data/fatfish_user_context`

```text
core.md
bindings.json
users/<user_hash>/intro.md
users/<user_hash>/memory.md
backups/persona/
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
python3 -B /home/ubuntu/AstrBot/data/plugins/astrbot_plugin_fatfish_user_context/selftest.py
```
