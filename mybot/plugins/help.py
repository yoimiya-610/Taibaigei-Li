from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="help",
    name="帮助菜单",
    default_enabled=True,
    scope="group",
    permission_level=2,
    privacy_level="public",
    backup_policy="none",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, Bot

from mybot.common.feature_flags import collect_features
from mybot.common.help_registry import (
    CATEGORY_META,
    HelpItem,
    collect_public_command_names,
    render_category_help,
    render_help_menu,
)
from mybot.common.legacy_games import LEGACY_GAMES, LEGACY_GAME_ORDER
from mybot.common.version import __version__


HELP_ITEMS = (
    HelpItem("趣味功能", "/游戏 - 查看历史小游戏玩法与开关", 5),
    HelpItem("签到积分", "/积分说明 - 查看积分规则", 40),
    HelpItem("系统说明", "/命令全览 - 查看全部命令", 5),
    HelpItem("系统说明", "/关于 - 本猫介绍", 10),
)
COMMAND_ALIASES = (
    "help", "帮助", "菜单", "功能", "命令", "功能菜单", "命令列表", "指令",
    "命令全览",
    "游戏", "游戏列表", "小游戏", "游戏大厅", "游戏大全",
    "关于", "about", "介绍",
    "积分说明", "积分帮助", "怎么赚积分", "积分规则", "怎么得积分",
    "诗词文艺", "情感互动", "趣味功能", "签到积分", "社交互动", "太白酒馆", "AI对话", "系统说明",
    "群管理介绍",
)

LEGACY_GAME_KEYS = LEGACY_GAME_ORDER


def _render_command_overview(
    group_id: str | int | None = None,
    user_id: str | int | None = None,
) -> str:
    commands = collect_public_command_names(group_id, user_id)
    lines = [
        "🧭 李太白给·命令全览 🧭",
        "=" * 22,
        "（摊开百门路引）群友可用的明面招式，尽在此卷。",
        "=" * 22,
    ]
    lines.append("｜".join(commands))
    lines.append("『百般门径皆成句，一卷翻开任君游。』")
    return "\n".join(lines)


def _event_group_id(event: MessageEvent) -> str | None:
    return str(event.group_id) if isinstance(event, GroupMessageEvent) else None


def _legacy_game_statuses(group_id: str | None = None) -> dict[str, str]:
    feature_map = {item["key"]: item for item in collect_features(group_id)}
    return {
        key: "已开启" if feature_map.get(key, {}).get("enabled") else "已关闭"
        for key in LEGACY_GAME_KEYS
    }


def _render_game_list(group_id: str | None = None) -> str:
    status = _legacy_game_statuses(group_id)
    lines = [
        "🎮 李太白给·游戏大厅 🎮",
        "======================",
        "（铺开旧局）六种玩法与指令都记在这里，默认收起：",
        "======================",
    ]
    for game in LEGACY_GAMES:
        lines.extend(
            [
                "",
                f"【{game.display_name}｜{status[game.feature_key]}】",
                "；".join(game.usage),
                game.summary,
            ]
        )
    lines.extend(
        [
            "",
            "======================",
            "/小游戏状态 - 查看六种游戏开关",
            "『旧局翻开凭兴致，得失且作一篇诗。』",
        ]
    )
    return "\n".join(lines)


# 帮助菜单
help_cmd = on_command("help", aliases={"帮助", "菜单", "功能", "功能菜单", "命令列表", "指令"}, priority=5, block=True)

@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    await help_cmd.finish(
        render_help_menu(_event_group_id(event), event.get_user_id())
    )

# 游戏列表
game_list = on_command("游戏", aliases={"游戏列表", "小游戏", "游戏大厅", "游戏大全"}, priority=5, block=True)

@game_list.handle()
async def handle_game_list(bot: Bot, event: MessageEvent):
    await game_list.finish(_render_game_list(_event_group_id(event)))


def _register_category_command(category: str):
    matcher = on_command(category, priority=5, block=True)

    @matcher.handle()
    async def handle_category_menu(bot: Bot, event: MessageEvent):
        text = render_category_help(
            category,
            _event_group_id(event),
            event.get_user_id(),
        )
        if not text:
            await matcher.finish(
                "（翻了翻空页）这卷眼下还没写内容。\n"
                "『卷中若暂无题字，改日添墨再来翻。』"
            )
        await matcher.finish(text)


for _category in CATEGORY_META:
    if _category != "太白酒馆":
        _register_category_command(_category)


command_overview = on_command("命令全览", priority=5, block=True)


@command_overview.handle()
async def handle_command_overview(event: MessageEvent):
    await command_overview.finish(
        _render_command_overview(_event_group_id(event), event.get_user_id())
    )

# 关于
about = on_command("关于", aliases={"about", "介绍"}, priority=5, block=True)

@about.handle()
async def handle_about(bot: Bot, event: MessageEvent):
    await about.finish(
        f"🎋 关于·李太白给 🎋\n"
        f"{'='*22}\n"
        f"（推了推墨镜，晃晃酒壶）\n"
        f"{'='*22}\n"
        f"\n"
        f"本猫名叫耄耋。\n"
        f"\n"
        f"白日里披着唐装在群中闲逛，夜深了便抱着酒壶听诸位谈天。\n"
        f"你若递来半句诗，本猫便陪你续到月落；你若心中烦闷，本猫也愿坐在旁边胡说几句，换你一笑。\n"
        f"偶尔嘴欠，偶尔多情，偶尔喝多了把豪言壮语当成诗念。至于本猫究竟有多少本事，不妨慢慢相处，亲自来翻。\n"
        f"\n"
        f"版本：v{__version__}\n"
        f"\n"
        f"『杯中藏月色，袖里有诗声。\n"
        f"有缘同席坐，便算故交人。』\n"
        f"{'='*22}\n"
        f"作者：悠依米亚\n"
        f"仓库：yoimiya-610/Taibaigei-Li\n"
        f"GitHub：[yoimiya-610/Taibaigei-Li](https://github.com/yoimiya-610/Taibaigei-Li)"
    )

# 积分说明
points_help = on_command("积分说明", aliases={"积分帮助", "怎么赚积分", "积分规则", "怎么得积分"}, priority=5, block=True)

@points_help.handle()
async def handle_points_help(bot: Bot, event: MessageEvent):
    await points_help.finish(
        f"💰 李太白给·积分指南 💰\n"
        f"{'='*22}\n"
        f"（拨了拨算盘）想攒点墨钱？本猫给你指条明路。\n"
        f"{'='*22}\n"
        f"【签到怎么算】\n"
        f"最终积分 = 今日签运基础分 + 连签加成 + 特殊事件增减。\n"
        f"若撞上“好运加倍”，便在前两步算完后再翻一番。\n"
        f"\n"
        f"/签到 是正途，签运越好，分数通常越多。\n"
        f"基础分大致是：天命之子/大凶 120，大吉 70，中吉 50，小吉 40，吉 35，末吉 30，小凶 25，中凶 23。\n"
        f"连签加成从连续 3 天起生效，按倍率慢慢抬升：3 天约 x1.1，往后逐步增加，365 天封顶 x3。\n"
        f"/补签 可补本年最近断签，首次 10 积分，之后翻倍。\n"
        f"/猜谜、/飞花令 也能攒分。\n"
        f"\n"
        f"/积分 看余额，/称号 看名号，/排行榜 看群内排行。\n"
        f"要紧的是常来常玩，莫想着一夜暴富。\n"
        f"『一分一墨慢慢攒，写到后来也成篇。』"
    )

