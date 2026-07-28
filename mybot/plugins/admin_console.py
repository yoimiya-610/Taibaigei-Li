import re

from nonebot import on_command, on_message

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.admin import get_admin_user_ids, is_admin_user, is_group_admin
from mybot.common.charm import change_charm
from mybot.common.feature_flags import (
    LEGACY_GAME_ORDER,
    collect_features,
    find_disabled_feature_for_message,
    get_feature_name,
    get_legacy_game_enabled,
    resolve_feature,
    set_feature_enabled,
)
from mybot.common.help_registry import HelpItem
from mybot.common.message_utils import get_first_at_user_id, get_message_text
from mybot.common.runtime_state import is_bot_enabled, toggle_bot_enabled
from mybot.common.titles import sync_user_titles
from mybot.common.user_utils import get_nickname
from mybot.plugins.points import add_points, get_points


HELP_ITEMS = (
    HelpItem("系统说明", "/功能列表 - 查看功能开关", 20),
)
COMMAND_ALIASES = (
    "功能列表",
    "功能状态",
    "开启功能",
    "关闭功能",
    "开启",
    "关闭",
)


def _admin_denied_message() -> str:
    if get_admin_user_ids():
        return "（合上账本）此乃掌柜权限，阁下暂不能翻。"
    return "（压低声音）尚未配置管理员，请先在 .env 设置 BOT_ADMINS=你的QQ号。"


async def _require_admin(matcher, event: MessageEvent) -> bool:
    if is_admin_user(event.get_user_id()):
        return True
    await matcher.finish(_admin_denied_message())
    return False


async def _require_group_admin(matcher, event: MessageEvent) -> bool:
    if is_group_admin(event):
        return True
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("（合上账本）群功能须在对应群中开合；全局符令只交系统掌柜。")
    await matcher.finish("（合上账本）此页只许本群掌柜与系统掌柜落笔。")
    return False


def _event_group_id(event: MessageEvent) -> str | None:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


def _normalize_command_text(message: str) -> str:
    text = message.strip()
    while text.startswith(("/", "／")):
        text = text[1:].lstrip()
    return text


def _is_debug_command_text(message: str) -> bool:
    text = _normalize_command_text(message).lower()
    return text == "debug" or text.startswith("debug ")


def bot_paused_rule(event: MessageEvent) -> bool:
    return not is_bot_enabled() and not _is_debug_command_text(get_message_text(event))


bot_pause_guard = on_message(rule=Rule(bot_paused_rule), priority=0, block=True)


@bot_pause_guard.handle()
async def handle_bot_paused():
    await bot_pause_guard.finish()


def _sorted_features(group_id: str | None = None) -> list[dict]:
    features = collect_features(group_id)
    return sorted(
        features,
        key=lambda item: (
            not item["protected"],
            item["name"],
            item["key"],
        ),
    )


def _resolve_feature_target(identifier: str, group_id: str | None = None) -> str | None:
    normalized = identifier.strip()
    if not normalized:
        return None

    if normalized.isdigit():
        index = int(normalized)
        features = _sorted_features(group_id)
        if 1 <= index <= len(features):
            return features[index - 1]["key"]
        return None

    return resolve_feature(normalized)


def _render_feature_list(group_id: str | None = None) -> str:
    lines = [
        "🛠 李太白给·功能开关 🛠",
        "=" * 22,
        "（翻账本）当前功能如下：",
        "=" * 22,
    ]

    for index, item in enumerate(_sorted_features(group_id), start=1):
        status = "开" if item["enabled"] else "关"
        locked = " / 保护" if item["protected"] else ""
        aliases = "、".join(item["aliases"][:4])
        alias_text = f"｜{aliases}" if aliases else ""
        lines.append(f"{index:02d}. {status} {item['key']} - {item['name']}{locked}{alias_text}")

    lines.extend(
        [
            "=" * 22,
            "用法：/关闭 序号 或 /关闭功能 功能名",
            "用法：/开启 序号 或 /开启功能 功能名",
        ]
    )
    return "\n".join(lines)


def disabled_feature_rule(event: MessageEvent) -> bool:
    return find_disabled_feature_for_message(
        get_message_text(event),
        _event_group_id(event),
    ) is not None


feature_guard = on_message(rule=Rule(disabled_feature_rule), priority=0, block=True)


@feature_guard.handle()
async def handle_disabled_feature(event: MessageEvent):
    feature = find_disabled_feature_for_message(
        get_message_text(event),
        _event_group_id(event),
    )
    feature_name = get_feature_name(feature) if feature else "该功能"
    await feature_guard.finish(
        f"（合上折扇）{feature_name} 暂时歇业中。\n"
        "如有疑惑，请联系管理员。"
    )


feature_list = on_command("功能列表", aliases={"功能状态"}, priority=3, block=True)


@feature_list.handle()
async def handle_feature_list(event: MessageEvent):
    await _require_group_admin(feature_list, event)
    await feature_list.finish(_render_feature_list(_event_group_id(event)))


enable_feature = on_command("开启功能", aliases={"开启"}, priority=3, block=True)


@enable_feature.handle()
async def handle_enable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _require_group_admin(enable_feature, event)
    group_id = _event_group_id(event)
    target = args.extract_plain_text().strip()
    feature = _resolve_feature_target(target, group_id)
    if not feature:
        await enable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    set_feature_enabled(feature, True, group_id)
    await enable_feature.finish(f"（本群账页落墨）已开启：{feature} - {get_feature_name(feature)}")


disable_feature = on_command("关闭功能", aliases={"关闭"}, priority=3, block=True)


@disable_feature.handle()
async def handle_disable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _require_group_admin(disable_feature, event)
    group_id = _event_group_id(event)
    target = args.extract_plain_text().strip()
    feature = _resolve_feature_target(target, group_id)
    if not feature:
        await disable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    try:
        set_feature_enabled(feature, False, group_id)
    except ValueError:
        await disable_feature.finish("（按住账本）管理员控制台不能关闭，否则就没人能开门了。")

    await disable_feature.finish(f"（本群账页收笔）已关闭：{feature} - {get_feature_name(feature)}")


global_enable_feature = on_command("全局开启功能", priority=3, block=True)
global_disable_feature = on_command("全局关闭功能", priority=3, block=True)


async def _handle_global_feature(
    matcher,
    event: MessageEvent,
    args: Message,
    enabled: bool,
) -> None:
    await _require_admin(matcher, event)
    target = args.extract_plain_text().strip()
    feature = _resolve_feature_target(target)
    if not feature:
        await matcher.finish("（翻总账）没找到这个功能名。输入 /功能列表 看看。")
    try:
        set_feature_enabled(feature, enabled)
    except ValueError:
        await matcher.finish("（按住总账）管理员控制台不能关闭，否则就没人能开门了。")
    action = "开启" if enabled else "关闭"
    await matcher.finish(
        f"（总账落印）已全局{action}：{feature} - {get_feature_name(feature)}；各群旧覆盖一并归零。"
    )


@global_enable_feature.handle()
async def handle_global_enable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _handle_global_feature(global_enable_feature, event, args, True)


@global_disable_feature.handle()
async def handle_global_disable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _handle_global_feature(global_disable_feature, event, args, False)


debug_cmd = on_command("debug", priority=4, block=True)


def _split_debug_args(raw_text: str) -> tuple[str, str]:
    parts = raw_text.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _parse_positive_amount(text: str) -> int | None:
    match = re.search(r"[-+]?\d+", text)
    if not match:
        return None
    try:
        amount = int(match.group())
    except ValueError:
        return None
    return amount if amount > 0 else None


def _debug_usage() -> str:
    return (
        "（压低声音）debug 符令这样写：\n"
        "/debug 1 开关本猫应答\n"
        "/debug 2 @某人 数字 添积分\n"
        "/debug 3 @某人 数字 添魅力\n"
        "/debug 4 开关六个历史小游戏"
    )


async def _require_group_debug(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    await debug_cmd.finish(
        "（合上暗账）这道 debug 令需在群里点名才作数。"
    )
    return ""


async def _handle_debug_points(bot: Bot, event: MessageEvent, args: Message, rest: str) -> None:
    group_id = await _require_group_debug(event)
    target_id = get_first_at_user_id(args)
    amount = _parse_positive_amount(rest)
    if not target_id or amount is None:
        await debug_cmd.finish("（拨算盘）用法：/debug 2 @某人 数字")

    record = add_points(target_id, group_id, amount)
    sync_user_titles(target_id, group_id, record)
    target_name = await get_nickname(bot, target_id, context="debug.points")
    await debug_cmd.finish(
        f"（拨动暗账）已为 {target_name} 添上 {amount} 积分。\n"
        f"当前积分：{record['current']}｜累计获得：{record['total']}"
    )


async def _handle_debug_charm(bot: Bot, event: MessageEvent, args: Message, rest: str) -> None:
    group_id = await _require_group_debug(event)
    target_id = get_first_at_user_id(args)
    amount = _parse_positive_amount(rest)
    if not target_id or amount is None:
        await debug_cmd.finish("（拂开花册）用法：/debug 3 @某人 数字")

    record = change_charm(target_id, group_id, amount)
    sync_user_titles(target_id, group_id, get_points(target_id, group_id))
    target_name = await get_nickname(bot, target_id, context="debug.charm")
    await debug_cmd.finish(
        f"（花册落墨）已为 {target_name} 添上 {amount} 魅力。\n"
        f"当前魅力：{record['charm']}"
    )


def _toggle_all_legacy_games() -> tuple[bool, str]:
    target_enabled = not all(get_legacy_game_enabled(feature) for feature in LEGACY_GAME_ORDER)
    for feature in LEGACY_GAME_ORDER:
        set_feature_enabled(feature, target_enabled)
    names = "、".join(get_feature_name(feature) for feature in LEGACY_GAME_ORDER)
    return target_enabled, names


@debug_cmd.handle()
async def handle_debug(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    await _require_admin(debug_cmd, event)
    action, rest = _split_debug_args(args.extract_plain_text())

    if action == "1":
        enabled = toggle_bot_enabled()
        if enabled:
            await debug_cmd.finish("（抖开唐装）本猫醒酒归来，诸令照常。")
        await debug_cmd.finish("（收起折扇）本猫暂且收声，除 /debug 外皆不应。")

    if action == "2":
        await _handle_debug_points(bot, event, args, rest)
        return

    if action == "3":
        await _handle_debug_charm(bot, event, args, rest)
        return

    if action == "4":
        enabled, names = _toggle_all_legacy_games()
        status = "开启" if enabled else "关闭"
        await debug_cmd.finish(f"（翻开旧局）六个历史小游戏已全部{status}：{names}")

    await debug_cmd.finish(_debug_usage())
