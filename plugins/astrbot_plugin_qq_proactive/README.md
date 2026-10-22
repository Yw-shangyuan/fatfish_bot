# 主动伴聊 QQ（astrbot_plugin_qq_proactive）

按人设在活跃时段内**主动**给绑定的 QQ 私聊发消息的小插件：LLM 决定"此刻要不要说话"，说得出人才会说的话，说不出口就沉默。

## 特性

- 五重防打扰：总开关 / 活跃时段（支持跨午夜）/ 每日硬上限 / 最小间隔 / LLM 可否决（PASS）
- 上下文记忆：自动记录绑定目标发来的最近消息，主动消息能接得上话
- 零手工配置：目标 UMO 用命令自动绑定

## 使用

1. 面板里配置 `API_KEY / API_BASE / MODEL / PERSONA`
2. 让 Bot 的 QQ 小号加主人好友并私聊，发送：`/proactive 绑定`
3. 试发一条：`/proactive 测试`
4. 查看运行情况：`/proactive 状态`；临时关闭：`/proactive 关`

## 命令

| 命令 | 说明 |
|:---|:---|
| `/proactive 绑定` | 把当前会话设为发送目标（写入配置） |
| `/proactive 解绑` | 解绑目标 |
| `/proactive 测试` | 立即生成并发送一条（计入今日配额） |
| `/proactive 状态` | 查看开关/目标/时段/今日计数 |
| `/proactive 开` `/proactive 关` | 临时开关 |

## 提醒

QQ 第三方协议登录有账号风控风险：`DAILY_LIMIT` 建议从 1~2 起步，观察几天再放大。
