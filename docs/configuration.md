# 配置参考

李太白给从 `mybot/.env` 读取本地配置。先复制 `mybot/.env.example`，再只在部署环境填写真实值；该文件被 Git 忽略。

## 启动前配置检查

无参数执行 `li-taibaigei` 或模块入口时，程序会先读取 `mybot/.env`，生成结构化检查结果，再初始化 NoneBot、加载业务插件和监听端口：

| 级别 | 启动行为 | 典型情况 |
| --- | --- | --- |
| `error` | 在绑定端口前退出，稳定返回退出码 `78` | Python 版本过低、非法 `HOST` / `PORT` / `COMMAND_START`、NoneBot 管理员格式会破坏初始化、运行目录不可写 |
| `warning` | 继续按既有方式启动 | 缺少 `.env`、管理员或 AI 密钥，自动化与保留策略参数使用安全默认值 |
| `info` | 继续启动 | 配置有效、使用既有默认值或可选能力已配置 |

检查覆盖 `PYTHON_VERSION`、`ENV_FILE`、`HOST`、`PORT`、`COMMAND_START`、`BOT_ADMINS` / `SUPERUSERS`、`DEEPSEEK_API_KEY`、`ONEBOT_ACCESS_TOKEN`、自动化参数，以及 `DATA_DIR`、`LOG_DIR`、`BACKUP_DIR` 的可写性。为兼容已有升级环境，如果存在 `GROUP_CHAT_LOG_RETENTION_DAYS`、`BACKUP_KEEP_DAYS`、`BACKUP_KEEP_COUNT`、`BACKUP_INCLUDE_GROUP_CHAT_LOGS` 或 `BACKUP_INCLUDE_IMAGE_LIBRARY`，预检也会校验其格式；非法保留策略值只产生 warning，并继续沿用既有安全降级行为。

诊断行只包含级别、变量名和固定修复建议，不插入原始配置值，因此不会显示密钥、QQ 号、群号或完整绝对路径。v0.7.1 不执行 OneBot 网络、登录状态或协议能力探测。

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

## 保留策略与图片库

这些配置均可选；未配置时不会自动删除既有运行记录。设置有限保留期前，应先在 Git 外备份数据并确认实际需要。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GROUP_CHAT_LOG_RETENTION_DAYS` | `0` | 群聊记录保留天数，0 表示不自动清理 |
| `BACKUP_KEEP_DAYS` | `0` | 备份保留天数，0 表示不按天数清理 |
| `BACKUP_KEEP_COUNT` | `0` | 最多保留备份份数，0 表示不按数量清理 |
| `BACKUP_INCLUDE_GROUP_CHAT_LOGS` | `true` | 备份是否包含群聊记录 |
| `BACKUP_INCLUDE_IMAGE_LIBRARY` | `false` | 备份是否包含图片库 |
| `IMAGE_LIBRARY_OCR_ENABLED` | `false` | 是否允许图片 OCR，需协议端支持 |
| `IMAGE_LIBRARY_MAX_FILE_MB` | `10` | 单张图片大小上限 |
| `IMAGE_LIBRARY_MAX_GROUP_MB` | `512` | 每群图片库总容量上限 |
| `IMAGE_LIBRARY_MAX_GROUP_IMAGES` | `500` | 每群收藏图片数量上限 |

非法保留策略不会触发自动清理。群聊记录和图片库属于群级功能，可通过管理员功能开关停止新增；关闭功能不会删除已有数据。图片库仅在显式收图时收藏，OCR 默认关闭。`/本群数据` 提供当前群采集与保留摘要，系统管理员可通过 `/系统诊断` 检查任务、存储和备份状态。

## 数据与隐私

- `mybot/data/` 可能包含用户 ID、群 ID、积分、语录、称号、功能开关和群聊记录。
- `mybot/logs/` 可能包含事件上下文与错误详情。
- `backups/` 是上述运行状态的本地副本。
- 群聊记录功能启用后会保存消息正文与 OneBot 消息段。

这些内容不得进入 Git。部署者需要自行确定访问权限、备份加密、保留周期和删除流程。
