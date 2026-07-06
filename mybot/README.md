# 李太白给

耄耋是一只穿唐装、戴墨镜、提酒壶的群聊猫诗人，基于 NoneBot2 与 OneBot v11。

## 启动

在包含 `mybot/` 的发布目录根目录执行：

```powershell
uv sync --project mybot
uv run --project mybot li-taibaigei
```

也可用标准模块入口启动：

```powershell
uv run --project mybot python -m mybot.main
```

首次运行前，将 `mybot/.env.example` 复制为 `mybot/.env`，填入自己的 API Key、连接配置、管理员 QQ 号和群号。`DAILY_GREET_GROUPS` 留空时不会发送定时早晚安问候。运行数据会保存在 `mybot/data/`，备份会保存在根目录 `backups/`；这些运行产物均不应提交到 Git。

历史小游戏源码会随发布包保留，但默认关闭；管理员可通过功能开关启用。

## 开发校验

```powershell
uv run --project mybot python -m compileall mybot/bot.py mybot/main.py mybot/common mybot/plugins mybot/plugins_disabled mybot/tests
uv run --project mybot python -m unittest discover -s mybot/tests -v
```
