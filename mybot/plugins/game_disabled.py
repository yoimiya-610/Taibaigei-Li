from nonebot import on_command

from mybot.common.feature_flags import collect_features, get_legacy_game_status, get_legacy_rotation_day_name
from mybot.common.help_registry import HelpItem


HELP_ITEMS = (
    HelpItem("小游戏", "/小游戏状态 - 查看游戏开关", 10),
)
COMMAND_ALIASES = ("小游戏状态", "历史小游戏")

LEGACY_PREFIX = "legacy_"
GAME_ORDER = (
    "legacy_slot",
    "legacy_dice",
    "legacy_blackjack",
    "legacy_race",
    "legacy_roulette",
)


def _render_game_status() -> str:
    feature_map = {
        item["key"]: item
        for item in collect_features()
        if item["key"].startswith(LEGACY_PREFIX)
    }
    games = [feature_map[key] for key in GAME_ORDER if key in feature_map]

    lines = [
        "🎮 李太白给·小游戏 🎮",
        "=" * 22,
        f"（翻旧卷）今日是{get_legacy_rotation_day_name()}，五种游戏开关如下：",
        "=" * 22,
    ]

    if not games:
        lines.append("旧玩法尚未载入。")
    else:
        for item in games:
            detail = get_legacy_game_status(item["key"])
            status = "已开启" if item["enabled"] else "已关闭"
            mode = detail["mode"]
            scheduled = "轮换开" if detail["scheduled"] else "轮换关"
            lines.append(f"{status}｜{item['name']}（{mode}，{scheduled}）")

    lines.extend(
        [
            "=" * 22,
            "周一到周五每日轮换一项，周六周日五局同开。",
            "（按住旧机括）这些老玩意一齐闹腾久了，服务器也要喘口气。\n5分钟内且先玩十次，容本猫给它缓缓劲。",
            "如有疑惑请联系管理员。",
            "『旧局藏于账本里，开合皆凭掌柜笔。』",
        ]
    )
    return "\n".join(lines)


game_status = on_command("小游戏状态", aliases={"历史小游戏"}, priority=5, block=True)


@game_status.handle()
async def handle_game_status():
    await game_status.finish(_render_game_status())
