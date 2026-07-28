# 李太白给 Python 包

本目录包含李太白给 v0.7.1 的 NoneBot2 应用、共享模块、插件和测试。仓库根目录是推荐的命令执行位置。

## 启动入口

```bash
uv sync --project mybot --locked
uv run --project mybot li-taibaigei
```

也可以使用模块入口：

```bash
uv run --project mybot python -m mybot.main
```

启动前将 `mybot/.env.example` 复制为 `mybot/.env`，并按 [配置参考](../docs/configuration.md) 填写本地值。AI 密钥、管理员 ID 和定时问候群组均可留空；OneBot V11 连接仍需在协议端完成配置。

两个入口都会先运行结构化配置预检；`error` 在 NoneBot 初始化、业务插件加载和端口绑定前以退出码 `78` 结束，`warning` 不阻止启动。预检不会执行 OneBot 网络探测，也不会输出任何配置值或完整绝对路径。

## 目录

- `common/`：配置、存储、权限、AI 客户端和共享业务逻辑。
- `plugins/`：默认加载的功能。
- `plugins_disabled/`：默认关闭、可由管理员启用的历史小游戏。
- `tests/`：完整单元测试。
- `data/`、`logs/`：运行时生成，禁止提交。

系统管理员由 `BOT_ADMINS` 或 NoneBot `SUPERUSERS` 配置。群主和群管理员只能管理所在群的群级功能开关。

## 开发验证

```bash
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
uv run --project mybot python -c "import mybot.bot; print('plugins-loaded')"
```
