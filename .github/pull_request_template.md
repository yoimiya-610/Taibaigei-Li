## 版本与变更

- 产品版本：
- 公开基线（如适用）：
- 用户可见变化：

## 仓库职责

- [ ] 变更属于本公开上游仓库
- [ ] 未覆盖或重建 Git 历史
- [ ] 第三方来源与再分发许可已记录

## 数据与部署影响

- 运行数据影响：
- 环境变量或连接配置：
- 升级步骤：
- 回滚方案：

## 验证

- [ ] `uv sync --project mybot --locked`
- [ ] `uv run --project mybot python tools/check_public_tree.py`
- [ ] `uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests`
- [ ] `uv run --project mybot python -m unittest discover -s mybot/tests -v`
- [ ] `bash -n tools/deploy_server.sh`
- [ ] `uv run --project mybot python -c "import mybot.bot; print('plugins-loaded')"`
- [ ] `git diff --check`

## 公开树检查

- [ ] 未提交 `.env`、真实 ID、密钥、Token 或私钥
- [ ] 未提交运行数据、日志、备份、数据库或本地适配器配置
- [ ] 未包含私有服务器路径、私有默认值、私有远端或运营记录
- [ ] 文档区分必需配置、可选 AI 配置和 NapCat/OneBot 配置
