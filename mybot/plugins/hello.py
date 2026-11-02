from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="hello",
    name="调试命令",
    default_enabled=True,
    scope="system",
    permission_level=None,
    privacy_level="internal",
    backup_policy="none",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

COMMAND_ALIASES = ("hello", "echo")

hello = on_command("hello", priority=10, block=True)

@hello.handle()
async def handle_hello(event: MessageEvent):
    await hello.finish(f"你好！你的QQ是 {event.get_user_id()}")

echo = on_command("echo", priority=10, block=True)

@echo.handle()
async def handle_echo(event: MessageEvent):
    msg = str(event.get_message()).replace("/echo", "").strip()
    if msg:
        await echo.finish(msg)
    else:
        await echo.finish("请在 /echo 后面加上内容")
