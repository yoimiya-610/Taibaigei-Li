from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot

from common.feature_flags import collect_features
from common.help_registry import HelpItem, render_help_menu


HELP_ITEMS = (
    HelpItem("签到积分", "/积分说明 - 查看积分规则", 40),
    HelpItem("系统说明", "/关于 - 本猫介绍", 10),
)
COMMAND_ALIASES = (
    "help", "帮助", "菜单", "功能", "命令",
    "游戏", "游戏列表", "小游戏",
    "关于", "about", "介绍",
    "积分说明", "积分帮助", "怎么赚积分",
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
        "（铺开旧局）玩法与指令都记在这里：\n"
        "======================\n"
        f"\n【图案转盘｜{status['legacy_slot']}】\n"
        "/图案转盘 金额\n"
        "转出三个相同图案可获对应倍数奖励，两个樱桃返还1.3倍；单次最多100积分。\n"
        f"\n【点数方块｜{status['legacy_dice']}】\n"
        "/点数挑战 开局；/选大 金额；/选小 金额；/选三同 金额；/结算\n"
        "三枚方块总和11-17为大、4-10为小，猜中大小得2倍，猜中三同得10倍；单次最多50积分。\n"
        f"\n【纸牌点数｜{status['legacy_blackjack']}】\n"
        "/纸牌挑战 金额；/要牌；/停牌；/弃牌\n"
        "点数尽量接近21且不可超过，普通胜局得2倍，开局21点得2.5倍；单次最多50积分。\n"
        f"\n【赛博竞速｜{status['legacy_race']}】\n"
        "/竞速 开局；/选马 编号 金额；/开跑；/取消竞速\n"
        "选择参赛者后等待开跑，所选参赛者夺冠即可得奖；单次最多50积分。\n"
        f"\n【多人转盘｜{status['legacy_roulette']}】\n"
        "/转盘 金额（单人）；/转盘挑战 金额；/加入转盘；/开始转盘；/转一轮；/取消转盘\n"
        "单人局通过安全格可得0.2倍奖励；多人局支持2至6人，最后留在局中的人获得积分池；单次最多100积分。\n"
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
        f"『杯中藏月色，袖里有诗声。\n"
        f"有缘同席坐，便算故交人。』\n"
        f"{'='*22}\n"
        f"作者：悠依米亚\n"
        f"GitHub：[yoimiya-610/Taibaigei-Li](https://github.com/yoimiya-610/Taibaigei-Li)"
    )

# 积分说明
points_help = on_command("积分说明", aliases={"积分帮助", "怎么赚积分"}, priority=5, block=True)

@points_help.handle()
async def handle_points_help(bot: Bot, event: MessageEvent):
    await points_help.finish(
        f"💰 李太白给·积分指南 💰\n"
        f"{'='*22}\n"
        f"（数钱）想知道怎么赚积分？\n"
        f"{'='*22}\n"
        f"\n"
        f"📈 【获取积分】\n"
        f"/签到 - 每日签到\n"
        f"  • 天命之子/大凶：100分\n"
        f"  • 大吉：50分\n"
        f"  • 中吉：30分\n"
        f"  • 小吉：20分\n"
        f"  • 吉：15分\n"
        f"  • 末吉：10分\n"
        f"  • 小凶：5分\n"
        f"  • 中凶：3分\n"
        f"  • 连续签到加成\n"
        f"  • 特殊事件加成\n"
        f"/补签 - 补最近断签，首次10积分，第二次起翻倍\n"
        f"\n"
        f"/猜谜 - 答对+20分\n"
        f"/飞花令 - 每句+15分\n"
        f"\n"
        f"{'='*22}\n"
        f"📊 /积分 - 查看余额\n"
        f"🎖 /称号 - 查看成就称号\n"
        f"🏷️ /佩戴称号 - 更换展示称号\n"
        f"🏆 /排行榜 - 积分排行\n"
        f"💬 /小酌档 /雅集档 /天命档 问题 - 付费对话\n"
        f"{'='*22}\n"
        f"『积分虽小情谊重，\n签到文娱两不误。\n细水长流终成海，\n日积月累见功夫~』"
    )

