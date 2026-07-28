# 部署指南

本指南部署李太白给的 NoneBot 端。OneBot V11 协议端应独立安装和维护。

## 前置条件

- Python 3.10 或更高版本。
- `uv`、`git`。
- 已运行的 OneBot V11 实现。
- 使用仓库更新脚本时还需要 `bash` 与 `screen`。

## 首次部署

```bash
git clone https://github.com/yoimiya-610/Taibaigei-Li.git
cd Taibaigei-Li
cp mybot/.env.example mybot/.env
```

编辑本地 `mybot/.env`，至少确认监听地址、端口和命令前缀。管理员、定时问候和 AI 配置均可稍后添加。完整字段见 [配置参考](configuration.md)。

安装锁定依赖并启动：

```bash
uv sync --project mybot --locked
uv run --project mybot li-taibaigei
```

也可以在 `mybot` 目录中使用模块入口：

```bash
cd mybot
uv run python -m mybot.main
```

## 连接 OneBot V11

推荐配置反向 WebSocket：NoneBot 作为服务端，协议端作为客户端。模板端口下的地址为：

```text
ws://127.0.0.1:8081/onebot/v11/ws
```

若设置了 `ONEBOT_ACCESS_TOKEN`，协议端必须配置同一个令牌。连接成功后，应在协议端和 NoneBot 日志中看到 WebSocket 建连信息。

NapCat 用户请按其 [官方安装文档](https://napneko.github.io/guide/install) 安装，再按 [官方接入文档](https://napneko.github.io/use/integration) 创建 WebSocket 客户端。本仓库不安装、更新、重启或重新登录 NapCat。

## 使用 Screen 运行

在仓库根目录执行：

```bash
cd mybot
screen -dmS nonebot uv run python bot.py
cd ..
```

查看会话：

```bash
screen -r nonebot
```

部署脚本默认只管理名为 `nonebot` 的 Screen 会话，不会操作其他会话或 OneBot 协议端。

## 更新

先阅读 [升级与回滚](upgrading.md) 并确认运行数据已备份。日常更新可在仓库根目录执行：

```bash
bash tools/deploy_server.sh
```

脚本行为：

1. 检查依赖命令与本地代码改动。
2. 在机器人仍运行时获取目标分支。
3. 仅接受可快进更新。
4. 只停止目标 NoneBot Screen 会话。
5. 快进代码并执行 `uv sync --locked`。
6. 恢复需要迁出的运行状态并重新启动 NoneBot。

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BOT_BRANCH` | `main` | 更新目标分支。 |
| `BOT_SCREEN_NAME` | `nonebot` | NoneBot Screen 会话名。 |
| `BOT_STOP_TIMEOUT` | `20` | 等待优雅停止的秒数。 |
| `BOT_START_WAIT` | `3` | 启动后检查会话的等待秒数。 |
| `RUNTIME_STATE_ROOT` | 当前用户目录 | 旧版本停止跟踪运行目录时的临时保存位置。 |

脚本发现本地源代码修改、非快进历史或启动失败时会停止并保留诊断信息，不会强制覆盖工作区。

## 数据与备份

运行状态位于 `mybot/data/`、`mybot/logs/` 和 `backups/`，均不受 Git 管理。备份至少应满足：

- 存储位置与源码 checkout 分离。
- 访问权限不宽于机器人运行账户。
- 如含群聊记录，应采用与消息数据相同的保护和删除策略。
- 升级前创建快照，升级验证后再按保留策略清理旧快照。

## 部署后检查

- OneBot WebSocket 已连接。
- 普通非 AI 命令可响应。
- 管理员权限符合本地配置。
- AI 密钥为空时，非 AI 功能仍正常。
- 数据、日志和备份目录未被 Git 跟踪。
