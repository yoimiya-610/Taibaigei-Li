# 李太白给

李太白给是基于 NoneBot2 与 OneBot V11 的中文群聊机器人。公开仓库只保留可分发源码；运行数据、日志、备份和本地环境配置都应留在部署环境，不进入 Git。

当前版本：`v0.1.5`

机器人主体位于 [`mybot/`](mybot/)。如果你拿到的是这个公开仓库副本，建议先阅读 [PUBLIC_RELEASE_MANIFEST.md](PUBLIC_RELEASE_MANIFEST.md) 了解发布包包含和剔除了什么。

## 快速开始

```powershell
Copy-Item mybot/.env.example mybot/.env
# 填写 DEEPSEEK_API_KEY、BOT_ADMINS 与 DAILY_GREET_GROUPS
uv sync --project mybot
uv run --project mybot li-taibaigei
```

也可以使用模块入口：

```powershell
uv run --project mybot python -m mybot.main
```

补充说明：

- `DAILY_GREET_GROUPS` 为空时会关闭定时早晚安。
- `mybot/data/`、`mybot/logs/` 和根目录 `backups/` 都属于运行产物，不应提交。
- 历史小游戏源码会随发布包保留，但默认关闭；管理员可在运行时开启。

## 仓库说明

- [mybot/README.md](mybot/README.md)：机器人运行说明。
- [docs/runtime-state-migration.md](docs/runtime-state-migration.md)：旧部署迁移到当前仓库结构时的状态迁移说明。
- [tools/deploy_server.sh](tools/deploy_server.sh)：服务器拉取更新与重启脚本。

## 部署更新

已有部署在首次切换到当前仓库结构前，请先阅读 [运行状态迁移说明](docs/runtime-state-migration.md)，避免 Git 删除历史上受跟踪的数据文件。

完成一次迁移后，可在服务器上执行：

```bash
cd ~/qqbot
bash tools/deploy_server.sh
```

脚本只在检测到可快进更新时，才短暂停止名为 `nonebot` 的 Screen 会话，更新代码和依赖后立即重启；它不会重启或重新登录 NapCat。

可选环境变量：

- `BOT_BRANCH`：默认 `main`
- `BOT_SCREEN_NAME`：默认 `nonebot`
- `BOT_STOP_TIMEOUT`：默认 `20` 秒

如果旧脚本里包含 `pkill -f screen`，不要继续用于日常更新；那会终止服务器上所有 Screen 会话，连同 NapCat 一并关闭。当前仓库的 `tools/deploy_server.sh` 只操作机器人对应的会话。
