# 李太白给

李太白给是基于 NoneBot2 与 OneBot V11 的中文群聊机器人。当前产品版本为 **v0.7.2**；从公开基线 **v0.7.0.1** 起，本仓库是公开产品的上游源仓库和协作入口。

代码采用 [MIT License](LICENSE)。运行数据、日志、备份、账号配置和密钥不属于源代码，也不得提交到 Git。

## 主要能力

- 签到、运势、积分、称号、礼物、榜单和群互动。
- 太白酒馆、诗词与趣味玩法；历史小游戏源码随版本保留，但默认关闭。
- 翻译、总结、润色、解释和多种本地文本转换工具。
- 群级功能开关与系统管理员控制台。
- 可选 AI 对话能力；未配置 AI 密钥时，非 AI 功能仍可使用。
- 可选群聊记录；记录内容属于敏感运行数据，只保存在部署环境。

## 快速开始

需要 Python 3.10 或更高版本、[uv](https://docs.astral.sh/uv/) 和一个 OneBot V11 实现。

```bash
git clone https://github.com/yoimiya-610/Taibaigei-Li.git
cd Taibaigei-Li
cp mybot/.env.example mybot/.env
uv sync --project mybot --locked
uv run --project mybot li-taibaigei
```

Windows PowerShell 可用下面的命令复制配置模板：

```powershell
Copy-Item mybot/.env.example mybot/.env
```

首次启动前请阅读 [配置参考](docs/configuration.md)。默认监听地址来自 `HOST` 与 `PORT`；OneBot V11 反向 WebSocket 地址通常为：

```text
ws://127.0.0.1:8081/onebot/v11/ws
```

启动命令会先执行配置预检，再初始化 NoneBot 和加载业务插件。致命错误会在绑定端口前以退出码 `78` 结束；warning 只提示可选能力或部署建议，不改变无参数 `li-taibaigei` 的启动方式。预检输出只包含变量名与修复建议，不打印密钥、账号标识或完整绝对路径。

## 配置分层

- 必需的服务配置：`HOST`、`PORT`、`COMMAND_START`，以及 OneBot 端的反向 WebSocket 连接。
- 推荐的管理配置：`BOT_ADMINS`；若连接配置使用令牌，再设置 `ONEBOT_ACCESS_TOKEN`。
- 可选的自动化配置：`DAILY_GREET_GROUPS`、`RANDOM_REPLY_CHANCE`、`BACKUP_HOUR`、`BACKUP_MINUTE`。
- 可选的 AI 配置：`DEEPSEEK_API_KEY`。留空不会阻止机器人启动。

所有真实 ID、令牌和密钥只能写入本地 `mybot/.env`，不得写入代码、文档示例或提交记录。

## NapCat / OneBot 支持边界

本仓库只维护李太白给的 NoneBot 端和 OneBot V11 接入说明，不再分发第三方 NapCat 安装脚本。NapCat 的安装、升级、登录和平台兼容性由其上游项目负责：

- [NapCat 官方安装文档](https://napneko.github.io/guide/install)
- [NapCat 接入框架文档](https://napneko.github.io/use/integration)
- [NoneBot OneBot V11 连接配置](https://onebot.adapters.nonebot.dev/docs/guide/setup/)

连接后会自动执行无副作用的 OneBot 只读能力探测，并由共享注册表区分
`supported`、`unsupported`、`unknown` 与 `degraded`。系统管理员可使用
`/系统诊断` 查看脱敏摘要；最低能力、可选增强能力和降级规则见
[OneBot 能力部署说明](docs/onebot-capabilities.md)。

## 运行数据

以下目录只属于部署环境，并已由 `.gitignore` 和公开树自检阻止提交：

- `mybot/data/`：积分、配置、群聊记录和游戏状态。
- `mybot/logs/`：运行日志。
- `backups/`：本地备份。
- `napcat/`、`lagrange/`：本地适配器及其配置。

群聊记录可能包含消息正文、用户 ID 和群 ID。启用前应确认适用的告知、授权、留存和删除要求。

## 文档

- [部署指南](docs/deployment.md)
- [配置参考](docs/configuration.md)
- [OneBot 最低能力与可选增强能力](docs/onebot-capabilities.md)
- [升级与回滚](docs/upgrading.md)
- [更新记录](Update.md)
- [贡献指南](CONTRIBUTING.md)

## 验证

```bash
uv sync --project mybot --locked
uv run --project mybot python tools/check_public_tree.py
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
bash -n tools/deploy_server.sh
uv run --project mybot python -c "import mybot.bot; print('plugins-loaded')"
```
