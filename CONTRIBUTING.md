# 贡献指南

感谢参与李太白给。公开基线 v0.7.0.1 起，本仓库是产品上游；功能、修复、文档和发布准备都应从这里发起。

## 开始前

1. 从最新 `main` 创建语义明确的分支。
2. 每个 Pull Request 聚焦一个目标。
3. 先说明用户可见行为、数据影响、配置变化和回滚方案。
4. 不从其他工作区整树复制内容；新增来源必须可审计并满足再分发许可。

## 禁止提交

- 真实 `.env`、API Key、Token、密码、私钥、QQ 号或群号。
- `mybot/data/`、`mybot/logs/`、`backups/` 中的运行产物。
- 数据库、归档、缓存、虚拟环境、构建元数据和本地 OneBot 配置。
- 私有服务器路径、私有远端、内部主机名或运营记录。
- 无法确认再分发权的第三方安装脚本或二进制文件。

## 代码约定

- 共享能力放在 `mybot/common/`，插件不要反向依赖其他插件。
- JSON 状态使用现有存储工具，保持并发写入和旧数据兼容。
- 用户提示保持李太白给角色语气；技术细节写日志。
- 新命令同步维护帮助项、别名、功能开关和测试。
- 运行路径使用仓库相对路径，不写个人机器或服务器的绝对路径。
- 修改版本时同步 `mybot/common/version.py`、`mybot/pyproject.toml`、`mybot/uv.lock` 和 `Update.md`。

## 本地验证

```bash
uv sync --project mybot --locked
uv run --project mybot python tools/check_public_tree.py
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
bash -n tools/deploy_server.sh
uv run --project mybot python -c "import mybot.bot; print('plugins-loaded')"
git diff --check
```

## Pull Request

PR 描述至少包含：

- 版本号与变更摘要。
- 用户和管理员影响。
- 运行数据、环境变量与部署影响。
- 实际执行的验证及结果。
- 兼容性、迁移与回滚方案。
- 第三方代码或素材的来源和许可证（如有）。

涉及群聊记录、积分、备份或功能开关时，要特别说明数据保留与旧版本兼容性。
