from mybot.common.plugin_metadata import declare_plugin


PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="personal_scroll",
    name="我的卷册",
    default_enabled=True,
    scope="group",
    permission_level=3,
    privacy_level="personal",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

from mybot.common.ai_public_play_guides import PublicPlayGuideEntry
from mybot.common.help_registry import HelpItem
from mybot.common.personal_scroll import render_personal_scroll
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("系统说明", "/我的卷册 - 汇总个人账册与公开贡献", 32),
)
COMMAND_ALIASES = ("我的卷册", "卷册", "个人卷册")
PUBLIC_PLAY_GUIDES = (
    PublicPlayGuideEntry(
        key="personal_scroll",
        keywords=("我的卷册", "卷册", "个人数据", "个人状态", "公开贡献", "礼物", "魅力"),
        intents=("查看", "查询", "汇总", "多少", "命令", "在哪"),
        public_explanation=(
            "/我的卷册 会按当前群统一展示积分、酒钱、称号、魅力、礼物库存摘要，"
            "以及本人入典、执笔、诗社和收图的公开贡献数量。"
        ),
        related_commands=("/我的卷册",),
    ),
)


PRIVATE_MESSAGE = (
    "（把卷册压回案上）积分、酒钱与名号都按群分卷，请到群里输入 /我的卷册。\n"
    "『卷页随群分旧章，\n"
    "独斟难把众名藏。\n"
    "待君重入诗朋座，\n"
    "本猫开卷细端详。』"
)

my_scroll = on_command(
    "我的卷册",
    aliases={"卷册", "个人卷册"},
    priority=5,
    block=True,
)


@my_scroll.handle()
async def handle_my_scroll(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await my_scroll.finish(PRIVATE_MESSAGE)

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    nickname = await get_nickname(bot, user_id, context="我的卷册")
    await my_scroll.finish(render_personal_scroll(user_id, group_id, nickname))
