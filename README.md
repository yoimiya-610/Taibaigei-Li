# 李太白给

基于 NoneBot2 与 OneBot V11 的中文群聊机器人。机器人代码位于 [`mybot/`](mybot/)，运行数据、日志和备份严格留在部署环境，不进入 Git。

## 本地启动

```powershell
Copy-Item mybot/.env.example mybot/.env
# 填写 DEEPSEEK_API_KEY、BOT_ADMINS 与 DAILY_GREET_GROUPS
uv sync --project mybot
uv run --project mybot li-taibaigei
```

`DAILY_GREET_GROUPS` 为空时会关闭定时早晚安；历史小游戏代码默认关闭，可由管理员在运行时开启。

## 协作方式

- 修改从分支发起，使用 Pull Request 合并到 `main`。
- 不提交 `.env`、`mybot/data/`、`mybot/logs/`、`backups/` 或本地适配器配置。
- 提交前运行：

```powershell
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
git diff --check
```

详细规则见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。

已有部署从旧版本升级时，请先阅读 [运行状态迁移说明](docs/runtime-state-migration.md)，避免 Git 删除历史上受跟踪的数据文件。

## 服务器更新

完成一次运行状态迁移后，服务器可使用下面的脚本更新代码：

```bash
cd ~/qqbot
bash tools/deploy_server.sh
```

脚本会在机器人仍运行时先拉取并校验更新；只有确实有可快进更新时，才短暂停止名为 `nonebot` 的 Screen 会话，更新代码和依赖后立即重新启动。它不会重启或重新登录 NapCat。

可选环境变量：`BOT_BRANCH`（默认 `main`）、`BOT_SCREEN_NAME`（默认 `nonebot`）、`BOT_STOP_TIMEOUT`（默认 `20` 秒）。脚本发现本地代码有未提交修改时会停止执行，避免覆盖人工改动。

不要在日常更新中继续使用旧的 `~/start_bot.sh`，如果它包含 `pkill -f screen`，会终止服务器上所有 Screen 会话，连同 NapCat 一并关闭。`tools/deploy_server.sh` 只操作 `nonebot` 会话，可替代该旧脚本。
