from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="game_disabled",
    name="小游戏状态",
    default_enabled=True,
    scope="group",
    permission_level=2,
    data_files=("data/legacy_game_overrides.json",),
    privacy_level="internal",
    backup_policy="standard",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from mybot.common.feature_flags import collect_features, get_legacy_game_status
from mybot.common.help_registry import HelpItem
from mybot.common.legacy_games import LEGACY_GAME_ORDER


# Keep the feature's existing administrator-control visibility without exposing
# this status command in the identity-independent public help menu.
HELP_ITEMS = (
    HelpItem(
        "趣味功能",
        "/小游戏状态 - 查看游戏开关",
        90,
        system_admin_only=True,
    ),
)
COMMAND_ALIASES = ("小游戏状态", "历史小游戏")
PUBLIC_COMMANDS = COMMAND_ALIASES

LEGACY_PREFIX = "legacy_"


def _render_game_status(group_id: str | None = None) -> str:
    feature_map = {
        item["key"]: item
        for item in collect_features(group_id)
        if item["key"].startswith(LEGACY_PREFIX)
    }
    games = [feature_map[key] for key in LEGACY_GAME_ORDER if key in feature_map]

    lines = [
        "🎮 李太白给·小游戏 🎮",
        "=" * 22,
        "（翻旧卷）六种旧局默认收起，开关如下：",
        "=" * 22,
    ]

    if not games:
        lines.append("旧玩法尚未载入。")
    else:
        for item in games:
            detail = get_legacy_game_status(item["key"], group_id=group_id)
            status = "已开启" if item["enabled"] else "已关闭"
            mode = detail["mode"]
            lines.append(f"{status}｜{item['name']}（{mode}）")

    lines.extend(
        [
            "=" * 22,
            "任意星期均默认关闭，只由管理员显式开启。",
            "（按住旧机括）这些老玩意一齐闹腾久了，服务器也要喘口气。\n5分钟内且先玩十次，容本猫给它缓缓劲。",
            "如有疑惑请联系管理员。",
            "『旧局藏于账本里，开合皆凭掌柜笔。』",
        ]
    )
    return "\n".join(lines)


game_status = on_command("小游戏状态", aliases={"历史小游戏"}, priority=5, block=True)


@game_status.handle()
async def handle_game_status(event: MessageEvent):
    group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else None
    await game_status.finish(_render_game_status(group_id))
