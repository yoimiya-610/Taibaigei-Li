# 部署指南

本指南部署李太白给的 NoneBot 端，OneBot V11 协议端独立维护。需要 Python 3.11 或更高版本、`uv`、`git`；Linux 自动更新还需要 Bash、systemd 及管理目标服务的权限。

## 首次启动

```bash
git clone https://github.com/yoimiya-610/Taibaigei-Li.git
cd Taibaigei-Li
cp mybot/.env.example mybot/.env
uv sync --project mybot --locked
uv run --project mybot li-taibaigei
```

Windows 复制模板使用 `Copy-Item mybot/.env.example mybot/.env`，启动命令相同。真实管理员、群号、密钥和令牌只填写在本地配置中。配置项见 [配置参考](configuration.md)。没有 AI 密钥时仍可使用非 AI 功能，定时问候目标为空时不发送问候。

无参数入口先检查配置，再加载插件、绑定端口。致命配置错误以状态 `78` 退出，只输出变量名和固定建议；warning 不阻止启动，也不显示配置值。

## 连接 OneBot V11

同机部署推荐让协议端作为反向 WebSocket 客户端连接：

```text
ws://127.0.0.1:8081/onebot/v11/ws
```

地址和端口须与 `HOST`、`PORT` 一致；若设置 `ONEBOT_ACCESS_TOKEN`，两端必须使用相同令牌。跨主机时使用协议端可达的地址，并配置令牌与访问控制。

NapCat 安装、更新与登录由其上游维护，参见 [官方安装指南](https://napneko.github.io/guide/install) 和 [接入说明](https://napneko.github.io/use/integration)。本项目的更新脚本只操作机器人服务。

建连后使用 `get_version_info`、`get_status` 做只读能力探测。系统管理员可用 `/系统诊断` 查看存储、任务和 OneBot 能力摘要；探测失败不会阻止启动。最低要求与降级行为见 [OneBot 能力说明](onebot-capabilities.md)。

## Linux systemd 托管

使用专门的非 root 账户运行机器人。以下示例假定运行账户、组均为 `taibaigei`，checkout 位于 `/opt/taibaigei`；部署者应先建立账户和目录，并确保该账户能读取代码、本地配置和虚拟环境，能写入 `mybot/data/`、`mybot/logs/`、`backups/`。

先完成锁定依赖同步，并在前台确认启动成功，再按 Ctrl+C 结束前台实例。复制 [服务模板](../tools/taibaigei.service.example)，按实际账户、组、checkout 路径修改 `User`、`Group`、`WorkingDirectory`、`ExecStart`：

```bash
sudo cp tools/taibaigei.service.example /etc/systemd/system/taibaigei.service
sudo systemctl daemon-reload
sudo systemctl enable --now taibaigei.service
sudo systemctl status taibaigei.service --no-pager
```

服务直接执行锁定环境中的入口，不需要 systemd 通过交互 shell 查找 uv。配置由程序从 checkout 的 `mybot/.env` 加载；不需要另设 `EnvironmentFile`。模板会在配置错误 `78` 时停止重试，修复配置后执行 `sudo systemctl restart taibaigei.service`。查看日志：

```bash
sudo journalctl -u taibaigei.service -n 80 --no-pager
```

从 Screen 升级时，先结束原机器人会话并确认原进程退出，再启用 systemd；不要同时运行两份机器人。Windows 可继续前台运行或由自己的进程管理器托管，不能执行本 Linux 更新脚本。

## 更新

先按 [升级与回滚](upgrading.md) 在 Git 外备份状态。以能够管理目标服务、运行 uv 并更新 checkout 的部署账户执行：

```bash
bash tools/deploy_server.sh
```

更新流程会先检查本地代码改动和服务配置，在当前机器人仍运行时获取 `origin/main`，只接受快进；随后停止目标 systemd 服务、更新代码和锁定依赖，再启动并核对 `active`、有效 `MainPID` 和进程存活。代码已是最新但服务异常时，也会尝试恢复服务。同步失败时尝试拉起已停止的服务，并输出诊断；它不会自动回退代码或数据。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `BOT_BRANCH` | `main` | 获取的目标分支 |
| `BOT_SERVICE_NAME` | `taibaigei.service` | 要管理的 systemd 服务 |
| `BOT_SYSTEMCTL_BIN` | `systemctl` | systemctl 可执行文件 |
| `BOT_START_WAIT` | `3` | 启动后检查等待秒数 |
| `RUNTIME_STATE_ROOT` | 当前用户目录 | 历史版本停止跟踪运行目录时的临时保存位置 |

自定义服务名时先导出 `BOT_SERVICE_NAME`。uv 必须在部署账户的 PATH 中；不要使用未安装 uv 的账户直接运行更新脚本。脚本不安装 systemd 服务，不迁移 Screen 会话，也不授予账户提权权限。

## 数据与验证

运行状态位于 `mybot/data/`、`mybot/logs/`、`backups/`，本地配置位于 `mybot/.env`，均不提交到 Git。备份可能包含消息、用户标识和密钥，应保存在访问受限的 Git 外目录。保留策略默认不自动清理；配置与图片库容量限制见配置参考。

部署完成后检查服务与 OneBot 连接、普通命令、管理员权限以及 `/系统诊断`。六个历史小游戏源码仍会加载，但每天默认关闭，需管理员显式启用。群聊记录、图片库和备份的采集与保留应由部署者按实际需求配置。
