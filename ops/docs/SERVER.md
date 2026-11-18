# 服务器总览（SERVER.md）

> 实测时间：2026-11-01 14:10 CST。数据以当时实际扫描为准，硬件、端口会变，改动后请顺手更新本文件。

## 1. 基本信息

| 项目 | 值 |
| --- | --- |
| 主机名 | DESKTOP-K8V2Q1R |
| 系统 | Ubuntu 24.04.4 LTS |
| 内核 | 6.8.0-138-generic |
| 架构 | x86_64 |
| CPU | AMD EPYC 7K62，2 vCPU |
| 公网 IP | 101.34.204.107（上海电信，轻量应用服务器） |
| 时区 | Asia/Shanghai（CST），chrony 对时 |

## 2. 资源占用（2026-11-01 14:10）

- 内存：总 3.6 GiB，已用 1.7 GiB，可用 2.0 GiB，缓存 2.0 GiB
- Swap：总 1.9 GiB，已用 154 MiB
- 磁盘：`/dev/vda2` 单盘挂 `/`，总 59G，已用 22G，剩余 35G（39%）

内存是这台机器的瓶颈：3.6 GiB 里 AstrBot + Docker 已占近一半。新增长驻服务前先看可用内存。

## 3. 磁盘占用大头

| 路径 | 大小 | 说明 |
| --- | --- | --- |
| /home/ubuntu/backups | 3.8G | 每日加密备份包（age），保留最近若干份 |
| /home/ubuntu/bot-src | 2.0G | 插件与运维脚本的 git 仓库（含备份分支历史） |
| /home/ubuntu/AstrBot | 701M | 机器人本体 + data |
| /srv/snowluma | 476M | QQ 协议端容器数据卷 |
| /home/ubuntu/ops | 200K | 运维脚本与中控面板 |

## 4. 用户与权限边界

- 运行身份：`ubuntu`（uid 1000），附加组：`sudo`、`docker`、`adm`、`video` 等
- AI 工具层**技术上可用 sudo**：实测 `sudo -n -l` 返回 `(ALL) NOPASSWD: ALL`。不改 sshd、不擅自重启 astrbot 属于**操作约定**，不是权限限制，详见 `接入须知.md` 第 4 节
- 可读写：`/home/ubuntu` 全域（AstrBot/data、plugins、logs、backups、ops）、`/srv/snowluma` 大部分
- 不可读：root 属主文件（如 `/etc/shadow`），snowluma 卷内少数 root 文件
- 注意：`docker` 组等价于宿主机 root（可 exec 进容器并挂载宿主目录），这是目前最大的权限口子

## 5. 对外暴露（云防火墙）

> 最后核对：2026-11-03 16:40，与腾讯云轻量防火墙页面逐条对照。

### 5.1 云防火墙已放行

| 协议/端口 | 防火墙备注 | 服务器上谁在听 | 公网实际可达性 |
| --- | --- | --- | --- |
| TCP 22 | Linux SSH登录 | sshd | 可达（暴力破解目标，见 §8） |
| TCP 80 | Web服务HTTP，如 Apache、Nginx | 无进程监听 | 口子开着但当前无人使用 |
| TCP 8765 | 网页取码 | qr_portal.py（fatfish-qr.service，肥鱼迷你中控） | 可达，明文 HTTP+URL token，见 §8 |
| ICMP | Ping | — | 可达 |

### 5.2 在监听、防火墙未放行（公网不可达）

| 端口 | 归属 | 用途 |
| --- | --- | --- |
| 3000/3001/5099/9210 | snowluma 容器（host 网络） | QQ 协议端与内部接口 |
| 5900 | x11vnc（Xvfb :1 栈） | VNC，rfbauth 在 /root/.vnc/passwd |
| 6081 | websockify/noVNC（99858） | 浏览器 VNC 入口 |
| 6185 | astrbot.service | **AstrBot WebUI 管理面板**，待放行 → 5.3 |
| 6199 | astrbot.service | 本机内部服务，永不外开 |

另：SERVICES.md 提到的临时 http.server 18080 当前未监听（已停）。

### 5.3 待放行（2026-11-03 决策）

- **TCP 6185**：AstrBot WebUI 管理面板（模型 provider 增删改、插件管理、日志查看），手机/PC 浏览器直接使用。
  - 操作：云防火墙添加规则 TCP 6185，备注建议填「AstrBot WebUI管理面板」。
  - 服务端已就绪：astrbot 监听 0.0.0.0:6185，放行即生效，无需改配置或重启。
  - 安全注意：登录用户名为自定义（非默认，口令已设 pbkdf2 哈希），但流量为明文 HTTP——公共网络下慎登；若不需要长期开放，用毕可在防火墙删除该条。
  - 放行后验证：浏览器打开 http://101.34.204.107:6185 出登录页即成。

## 6. 目录地图

    /home/ubuntu
      AstrBot/            机器人本体
        data/             配置(cmd_config.json)、plugins、logs、knowledge_base、workspaces、data_v4.db
        .venv/            Python 虚拟环境
      bot-src/            源码备份仓库（GitHub: Yw-shangyuan/fatfish_bot）
        plugins/          插件源码副本
        ops/              运维脚本副本
      backups/data/       *.tar.gz.age 加密备份包 + .sha256
      ops/                运维脚本、中控面板、fishbox 原型
        docs/             本套文档
      backup-data.sh      数据备份（cron 每 3 天 04:20）
      backup-src.sh       源码备份（手动触发）
      deploy.sh           部署脚本

## 7. 备份策略

- 数据：`/home/ubuntu/backup-data.sh`，cron `20 4 */3 * *`
  - 流程：停 snowluma 容器与 astrbot 服务 → tar 冷拷贝（排除日志/表情/崩溃转储）→ age 加密 → 推 GitHub 孤立分支 `backup-YYYYMMDD-HHMM` → 重启服务 → QQ 通知
  - 内容范围：`home/ubuntu/AstrBot/data`、`srv/napcat`、`srv/snowluma`、`etc/systemd/system/astrbot.service`
  - 校验：同目录 `.sha256`
- 源码：`/home/ubuntu/backup-src.sh`，手动执行，rsync 到 bot-src 后提交推 `main`
- 解密需要 age 私钥，私钥不在服务器上

## 8. 安全现状与待办

现状：
- sshd 仍允许密码登录，且 `PermitRootLogin yes`
- 22 端口对全网开放，属暴力破解高频目标
- 8765 为明文 HTTP，token 出现在 URL 中（页面刷新即暴露在链路日志）
- AI 侧持有 docker 组权限

建议（按收益排序）：
1. 配好密钥后关闭 `PasswordAuthentication`，`PermitRootLogin` 改 `prohibit-password`
2. 装 fail2ban，规则覆盖 sshd
3. 8765 优先走 ssh 隧道（`ssh -L 8765:127.0.0.1:8765`），或前置 nginx + TLS
4. 80 端口无服务时关闭
5. AI 侧如需长期用，考虑从 docker 组移出，改用受限的 socket-proxy
