# 运行状态迁移

本仓库从此版本起不再跟踪 `mybot/data/`、`mybot/logs/` 与 `backups/`。新部署无需额外操作；已有部署必须在首次拉取该变更前迁出运行状态，避免 Git 的文件删除影响本地数据。

## 旧部署升级

1. 停止机器人进程。
2. 在仓库根目录执行以下命令，将当前状态移到仓库外：

```bash
state="/root/qqbot_runtime_state_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$state"

mv mybot/data "$state/live_data"
[ -d mybot/logs ] && mv mybot/logs "$state/live_logs"
[ -d backups ] && mv backups "$state/live_backups"
```

3. 拉取代码并更新依赖：

```bash
git pull --ff-only origin main
cd mybot
uv sync --locked
cd ..
```

4. 恢复原来的运行状态：

```bash
cp -a "$state/live_data" mybot/data
[ -d "$state/live_logs" ] && cp -a "$state/live_logs" mybot/logs
[ -d "$state/live_backups" ] && cp -a "$state/live_backups" backups
```

5. 重启机器人并确认 OneBot 已连接。

不要使用 `git reset --hard` 或 `git clean -fdx` 清理部署目录；这两条命令可能移除未跟踪的运行状态。

完成这次迁移后，后续服务器更新使用：

```bash
cd ~/qqbot
bash tools/deploy_server.sh
```

该脚本只重启 NoneBot 的 `screen` 会话，不会重启或要求重新登录 NapCat。脚本会先完成远程拉取检查；没有新提交时不会重启机器人。

旧的 `~/start_bot.sh` 若使用 `pkill -f screen`，会同时终止 NapCat 的 Screen 会话；不要将其用于日常更新。
