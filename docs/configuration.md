# 配置参考

李太白给从 `mybot/.env` 读取本地配置。先复制 `mybot/.env.example`，再只在部署环境填写真实值；该文件被 Git 忽略。

## 必需的服务配置

| 变量 | 模板值 | 说明 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | NoneBot 监听地址。同机部署 OneBot 时保持环回地址即可。 |
| `PORT` | `8081` | NoneBot 监听端口，需与 OneBot 反向 WebSocket 地址一致。 |
| `COMMAND_START` | `["/"]` | NoneBot 命令前缀集合。 |

服务启动后，还必须在 OneBot V11 实现端配置连接。推荐让协议端作为 WebSocket 客户端，连接：

```text
ws://127.0.0.1:8081/onebot/v11/ws
```

`127.0.0.1` 和 `8081` 应分别替换为协议端可访问的 `HOST` 与 `PORT`。容器或跨主机部署时，不要把环回地址误当作另一容器或主机。

## 管理与自动化配置

| 变量 | 默认值 | 是否必需 | 说明 |
| --- | --- | --- | --- |
| `BOT_ADMINS` | 空 | 推荐 | 逗号分隔的系统管理员 ID。为空时系统级管理命令不可用。 |
| `DAILY_GREET_GROUPS` | 空 | 否 | 逗号分隔的早晚安目标群组；为空时关闭定时问候。 |
| `RANDOM_REPLY_CHANCE` | `0.01` | 否 | 群聊随机应答概率，程序会限制在 0 到 1。 |
| `BACKUP_HOUR` | `3` | 否 | 每日备份小时，范围 0 到 23。 |
| `BACKUP_MINUTE` | `0` | 否 | 每日备份分钟，范围 0 到 59。 |

NoneBot 的 `SUPERUSERS` 也会被权限判断识别。不要把任何真实 ID 写入公开模板、测试或文档。

## 可选 AI 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 空 | 用于 AI 对话、翻译、总结、润色和解释等能力。 |

密钥留空时机器人仍可启动，本地工具和非 AI 功能仍可使用；调用依赖 AI 的能力时会返回可理解的失败提示。密钥只应保存在本地 `.env` 或部署平台的秘密管理中。

## OneBot 访问令牌

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ONEBOT_ACCESS_TOKEN` | 空 | OneBot V11 双向连接的访问令牌。 |

如果协议端配置了令牌，NoneBot 与协议端必须使用相同值。跨容器、跨主机或非可信网络部署时建议启用令牌，并配合网络访问控制。不要把 NapCat WebUI 令牌和 OneBot 访问令牌混为一谈。

参考：

- [NoneBot OneBot V11 连接配置](https://onebot.adapters.nonebot.dev/docs/guide/setup/)
- [NoneBot OneBot 访问令牌配置](https://onebot.adapters.nonebot.dev/docs/guide/configuration/)
- [NapCat 接入框架](https://napneko.github.io/use/integration)

## NapCat 支持边界

NapCat 是可选的第三方 OneBot 实现，不属于本仓库。李太白给只保证 OneBot V11 适配层与文档中的连接方式；NapCat 的安装、QQ 登录、更新、WebUI、安全设置和平台兼容性由其上游项目负责。

本仓库不保存 NapCat 配置，也不再分发 NapCat 安装脚本。请使用 [NapCat 官方安装文档](https://napneko.github.io/guide/install)。

## 数据与隐私

- `mybot/data/` 可能包含用户 ID、群 ID、积分、语录、称号、功能开关和群聊记录。
- `mybot/logs/` 可能包含事件上下文与错误详情。
- `backups/` 是上述运行状态的本地副本。
- 群聊记录功能启用后会保存消息正文与 OneBot 消息段。

这些内容不得进入 Git。部署者需要自行确定访问权限、备份加密、保留周期和删除流程。
