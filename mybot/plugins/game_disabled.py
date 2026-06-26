from nonebot import on_command

from common.feature_flags import collect_features
from common.help_registry import HelpItem


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
        "（翻旧卷）五种游戏开关如下：",
        "=" * 22,
    ]

    if not games:
        lines.append("旧玩法尚未载入。")
    else:
        for item in games:
            status = "已开启" if item["enabled"] else "已关闭"
            lines.append(f"{status}｜{item['name']}")

    lines.extend(
        [
            "=" * 22,
            "如有疑惑请联系管理员。",
            "『旧局藏于账本里，开合皆凭掌柜笔。』",
        ]
    )
    return "\n".join(lines)


game_status = on_command("小游戏状态", aliases={"历史小游戏"}, priority=5, block=True)


@game_status.handle()
async def handle_game_status():
    await game_status.finish(_render_game_status())
