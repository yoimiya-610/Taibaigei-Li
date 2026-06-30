from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot

from mybot.common.feature_flags import collect_features, get_legacy_rotation_day_name
from mybot.common.help_registry import CATEGORY_META, HelpItem, render_category_help, render_help_menu
from mybot.common.version import __version__


HELP_ITEMS = (
    HelpItem("签到积分", "/积分说明 - 查看积分规则", 40),
    HelpItem("系统说明", "/关于 - 本猫介绍", 10),
)
COMMAND_ALIASES = (
    "help", "帮助", "菜单", "功能", "命令",
    "游戏", "游戏列表", "小游戏",
    "关于", "about", "介绍",
    "积分说明", "积分帮助", "怎么赚积分",
    "诗词文艺", "情感互动", "趣味功能", "签到积分", "社交互动", "AI对话", "系统说明",
)

LEGACY_GAME_KEYS = (
    "legacy_slot",
    "legacy_dice",
    "legacy_blackjack",
    "legacy_race",
    "legacy_roulette",
)


def _legacy_game_statuses() -> dict[str, str]:
    feature_map = {item["key"]: item for item in collect_features()}
    return {
        key: "已开启" if feature_map.get(key, {}).get("enabled") else "已关闭"
        for key in LEGACY_GAME_KEYS
    }


def _render_game_list() -> str:
    status = _legacy_game_statuses()
    return (
        "🎮 李太白给·游戏大厅 🎮\n"
        "======================\n"
        f"（铺开旧局）今日是{get_legacy_rotation_day_name()}，玩法与指令都记在这里：\n"
        "======================\n"
        f"\n【图案转盘｜{status['legacy_slot']}】\n"
        "/图案转盘 金额\n"
        "转出三个相同图案可获对应倍数奖励，两个樱桃返还1.25倍；单次最多100积分。\n"
        f"\n【点数方块｜{status['legacy_dice']}】\n"
        "/点数挑战 开局；/选大 金额；/选小 金额；/选三同 金额；/结算\n"
        "三枚方块总和11-17为大、4-10为小，猜中大小得1.95倍，猜中三同得34倍；单次最多100积分。\n"
        f"\n【纸牌点数｜{status['legacy_blackjack']}】\n"
        "/纸牌挑战 金额；/要牌；/停牌；/弃牌\n"
        "点数尽量接近21且不可超过，普通胜局得1.95倍，开局21点得2.4倍；单次最多100积分。\n"
        f"\n【赛博竞速｜{status['legacy_race']}】\n"
        "/竞速 开局；/选马 编号 金额；/开跑；/取消竞速\n"
        "选择参赛者后等待开跑，所选参赛者夺冠按奖池折算分账，保底约1.9倍；单次最多100积分。\n"
        f"\n【多人转盘｜{status['legacy_roulette']}】\n"
        "/转盘 金额（单人）；/转盘挑战 金额；/加入转盘；/开始转盘；/转一轮；/取消转盘\n"
        "单人局通过安全格可得0.15倍奖励；多人局支持2至6人，最后留在局中的人获得95%积分池；单次最多100积分。\n"
        "\n======================\n"
        "/小游戏状态 - 查看五种游戏开关\n"
        "『旧局翻开凭兴致，得失且作一篇诗。』"
    )


# 帮助菜单
help_cmd = on_command("help", aliases={"帮助", "菜单", "功能"}, priority=5, block=True)

@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    await help_cmd.finish(render_help_menu())

# 游戏列表
game_list = on_command("游戏", aliases={"游戏列表", "小游戏"}, priority=5, block=True)

@game_list.handle()
async def handle_game_list(bot: Bot, event: MessageEvent):
    await game_list.finish(_render_game_list())


def _register_category_command(category: str):
    matcher = on_command(category, priority=5, block=True)

    @matcher.handle()
    async def handle_category_menu(bot: Bot, event: MessageEvent):
        text = render_category_help(category)
        if not text:
            await matcher.finish(
                "（翻了翻空页）这卷眼下还没写内容。\n"
                "『卷中若暂无题字，改日添墨再来翻。』"
            )
        await matcher.finish(text)


for _category in CATEGORY_META:
    if _category != "小游戏":
        _register_category_command(_category)

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
points_help = on_command("积分说明", aliases={"积分帮助", "怎么赚积分"}, priority=5, block=True)

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

