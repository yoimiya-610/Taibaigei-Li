# 贡献指南

## 分支与 PR

1. 从最新 `main` 创建描述明确的分支，例如 `fix/fortune-copy` 或 `feat/quote-search`。
2. 每个 Pull Request 聚焦一个目标；行为变化、数据迁移和重构不要混在同一 PR。
3. PR 描述必须说明用户可见变化、数据兼容性、验证命令，以及是否需要更新部署环境变量。
4. 合并前 CI 必须通过。涉及积分、签到、备份或功能开关时，应额外说明回滚方案。

## 禁止提交的内容

- API Key、Token、QQ 号、群号、WebUI 配置或真实 `.env`。
- `mybot/data/` 中的积分、签到、语录、称号和群配置。
- `mybot/logs/`、`backups/`、虚拟环境、数据库和临时文件。

旧部署升级到移除运行产物的版本前，先按 [运行状态迁移说明](docs/runtime-state-migration.md) 迁出并恢复本地状态。

## 本地验证

```powershell
uv sync --project mybot --locked
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
git diff --check
```

## 文案与架构

遵循 [AGENTS.md](AGENTS.md)：用户侧文案保持李太白给角色语气，技术错误写日志；共享能力放在 `mybot/common/`，避免插件间反向依赖。
