# 李太白给公开仓库协作规则

本文件适用于自动化代理和开发者。公开基线 v0.7.0.1 起，本仓库是李太白给公开产品的上游源仓库。

## 硬规则

- 一个任务对应一个分支和一个聚焦的 Pull Request。
- 开始前同步最新 `origin/main`，结束前检查完整 diff。
- 保留本仓库的 Git、CI、Issue 和 PR 历史，不覆盖或重建历史。
- 不从未知或私有工作区整树复制；导入必须有明确来源、清单和许可。
- 不提交运行数据、日志、备份、密钥、真实 ID、本地配置、数据库或私有默认值。
- 不加入个人路径、私有服务器信息、私有远端或运营记录。
- 第三方文件只有在来源和再分发许可均明确时才能进入仓库。

## 项目结构

- `mybot/bot.py`：NoneBot 初始化、OneBot V11 适配器和插件加载。
- `mybot/common/`：共享配置、存储、权限和业务工具。
- `mybot/plugins/`：默认加载的功能插件。
- `mybot/plugins_disabled/`：默认关闭、运行时可开启的历史小游戏。
- `mybot/tests/`：单元与回归测试。
- `tools/check_public_tree.py`：公开树隐私与禁止文件检查。
- `tools/deploy_server.sh`：仅更新并重启 NoneBot 进程的部署脚本。
- `docs/`：部署、配置与升级文档。

`mybot/data/`、`mybot/logs/`、`backups/` 和本地适配器目录均为运行时内容，不属于源码。

## 实现要求

- 共享能力放在 `common/`；避免插件之间形成反向依赖。
- AI 请求统一通过共享客户端；缺少可选密钥时必须优雅失败。
- JSON 读写使用现有带锁工具，保持旧状态结构兼容。
- 禁止裸 `except:`；记录技术上下文，用户侧使用角色化提示。
- 新功能声明命令别名、帮助项和必要的功能开关。
- 历史小游戏默认关闭是产品策略，不得无意开启。
- 群聊记录属于敏感数据；修改时同时考虑开关、留存和删除边界。
- 所有运行路径使用仓库相对位置。

## 文档与版本

面向公开用户的文档必须清楚区分：

- 启动所需的服务与 OneBot 配置。
- 可选的 AI、管理和自动化配置。
- NapCat 等第三方协议端的安装责任与支持边界。
- 数据影响、升级步骤和回滚方案。

版本更新必须同步以下四处：

- `mybot/common/version.py`
- `mybot/pyproject.toml`
- `mybot/uv.lock`
- `Update.md`

## 验证

提交前至少执行：

```bash
uv sync --project mybot --locked
uv run --project mybot python tools/check_public_tree.py
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
bash -n tools/deploy_server.sh
uv run --project mybot python -c "import mybot.bot; print('plugins-loaded')"
git diff --check
```

PR 描述必须写明版本、用户影响、数据与部署影响、验证结果和回滚方案。不要创建正式 GitHub Release，除非任务明确要求。
