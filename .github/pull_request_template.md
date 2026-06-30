## 变更内容

<!-- 简述用户可见行为与实现范围。 -->

## 数据与部署影响

- [ ] 不涉及运行数据格式或迁移
- [ ] 不涉及环境变量或部署配置
- [ ] 已说明兼容性、迁移或回滚方案

## 验证

- [ ] `uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests`
- [ ] `uv run --project mybot python -m unittest discover -s mybot/tests -v`
- [ ] `git diff --check`

## 检查清单

- [ ] 未提交 `.env`、运行数据、日志、备份或本地适配器配置
- [ ] 用户侧文案符合李太白给角色语气
- [ ] 已更新帮助文案、文档或测试（如适用）
