from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="admin_console",
    name="管理员控制台",
    default_enabled=True,
    scope="system",
    permission_level=None,
    data_files=(
        "data/admin_audit.json",
        "data/admin_permissions.json",
        "data/feature_flags.json",
        "data/legacy_game_overrides.json",
        "data/runtime_state.json",
    ),
    privacy_level="sensitive",
    backup_policy="standard",
    protected=True,
)

import re

from nonebot import on_command, on_message

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.admin import (
    PERMISSION_LEVEL_NAMES,
    get_event_permission_level,
    get_feature_permission_level,
    get_group_permission_level,
    has_command_permission,
    is_admin_user,
    normalize_id,
    normalize_permission_level,
    set_group_permission_level,
)
from mybot.common.admin_audit import record_admin_action
from mybot.common.charm import change_charm, get_charm
from mybot.common.feature_flags import (
    LEGACY_GAME_ORDER,
    collect_features,
    find_disabled_feature_for_message,
    get_feature_name,
    get_legacy_game_enabled,
    is_feature_enabled,
    resolve_feature,
    set_feature_enabled,
)
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.message_utils import get_first_at_user_id, get_message_text
from mybot.common.runtime_state import is_bot_enabled, toggle_bot_enabled
from mybot.common.titles import sync_user_titles
from mybot.common.user_utils import get_nickname
from mybot.common.accounting import add_points, get_points


logger = get_plugin_logger(__name__)


HELP_ITEMS = (
    HelpItem(
        "系统说明",
        "/功能列表 - 查看有权管理的群功能",
        20,
        min_permission_level=1,
    ),
    HelpItem(
        "系统说明",
        "/管理员 - 管理群聊权限",
        21,
        system_admin_only=True,
    ),
)
COMMAND_ALIASES = (
    "管理员",
    "功能列表",
    "功能状态",
    "开启功能",
    "关闭功能",
    "开启",
    "关闭",
)


def _admin_denied_message() -> str:
    return "（合上总册）此卷只交系统掌柜过目。"


async def _require_admin(matcher, event: MessageEvent) -> bool:
    if is_admin_user(event.get_user_id()):
        return True
    await matcher.finish(_admin_denied_message())
    return False


async def _require_group_admin(matcher, event: MessageEvent) -> bool:
    if is_admin_user(event.get_user_id()):
        return True
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("（合上账本）群功能须在对应群中开合；全局符令只交系统掌柜。")
    if has_command_permission(event, "feature_list"):
        return True
    await matcher.finish("（合上账本）此页尚未向阁下开卷。")
    return False


def _event_group_id(event: MessageEvent) -> str | None:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


def _audit_action(
    event: MessageEvent,
    *,
    action: str,
    scope: str,
    target_group_id: str | None = None,
    target_user_id: str | None = None,
    details: dict | None = None,
) -> str:
    try:
        record_admin_action(
            actor_user_id=event.get_user_id(),
            action=action,
            scope=scope,
            source_group_id=_event_group_id(event),
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            details=details,
        )
    except Exception as exc:
        logger.exception("管理员审计落盘失败 action=%s: %s", action, exc)
        return "\n（封印簿未能落印，请系统掌柜即刻查看 /系统诊断。）"
    return ""


def _parse_optional_group_id(raw_text: str) -> str | None:
    parts = raw_text.strip().split()
    if not parts:
        return None
    if len(parts) != 1:
        raise ValueError("invalid_group_args")
    return normalize_id(parts[0], "group_id")


def _parse_feature_toggle_args(raw_text: str) -> tuple[str, str | None]:
    parts = raw_text.strip().split()
    if len(parts) not in {1, 2}:
        raise ValueError("invalid_feature_toggle_args")
    group_id = normalize_id(parts[1], "group_id") if len(parts) == 2 else None
    return parts[0], group_id


def _resolve_group_command_target(
    event: MessageEvent,
    requested_group_id: str | None,
) -> str:
    if requested_group_id is not None:
        if not is_admin_user(event.get_user_id()):
            raise PermissionError("cross_group_system_admin_only")
        return requested_group_id
    group_id = _event_group_id(event)
    if group_id is None:
        raise ValueError("group_id_required")
    return group_id


def _public_features_only(event: MessageEvent) -> bool:
    return not is_admin_user(event.get_user_id())


def _feature_visible_to_event(event: MessageEvent, feature: dict) -> bool:
    if is_admin_user(event.get_user_id()):
        return True
    level = get_event_permission_level(event)
    required_level = get_feature_permission_level(feature["key"])
    if level == 1:
        return bool(feature["public"]) and required_level is not None
    return required_level is not None and required_level <= level


def _sorted_features_for_event(
    event: MessageEvent,
    group_id: str | None,
) -> list[dict]:
    return [
        item
        for item in _sorted_features(group_id)
        if _feature_visible_to_event(event, item)
    ]


def _resolve_feature_for_event(
    event: MessageEvent,
    identifier: str,
    group_id: str,
) -> str | None:
    features = _sorted_features_for_event(event, group_id)
    normalized = identifier.strip()
    if not normalized:
        return None
    if normalized.isdigit():
        index = int(normalized)
        return features[index - 1]["key"] if 1 <= index <= len(features) else None
    feature = resolve_feature(normalized)
    return feature if feature in {item["key"] for item in features} else None


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


def _sorted_features(
    group_id: str | None = None,
    public_only: bool = False,
) -> list[dict]:
    features = collect_features(group_id)
    if public_only:
        features = [item for item in features if item["public"]]
    return sorted(
        features,
        key=lambda item: (
            not item["protected"],
            item["name"],
            item["key"],
        ),
    )


def _resolve_feature_target(
    identifier: str,
    group_id: str | None = None,
    public_only: bool = False,
) -> str | None:
    normalized = identifier.strip()
    if not normalized:
        return None

    features = _sorted_features(group_id, public_only)
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(features):
            return features[index - 1]["key"]
        return None

    feature = resolve_feature(normalized)
    visible_keys = {item["key"] for item in features}
    return feature if feature in visible_keys else None


def _render_feature_list(
    group_id: str | None = None,
    public_only: bool = False,
) -> str:
    lines = [
        "🛠 李太白给·功能开关 🛠",
        "=" * 22,
        "（翻账本）当前功能如下：",
        "=" * 22,
    ]

    for index, item in enumerate(_sorted_features(group_id, public_only), start=1):
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


def _render_feature_list_for_event(event: MessageEvent, group_id: str) -> str:
    features = _sorted_features_for_event(event, group_id)
    lines = [
        "🛠 李太白给·功能开关 🛠",
        "=" * 22,
        f"（翻群 {group_id} 账本）阁下当前权限：{get_event_permission_level(event)} 级",
        "=" * 22,
    ]
    for index, item in enumerate(features, start=1):
        status = "开" if item["enabled"] else "关"
        required = get_feature_permission_level(item["key"])
        permission = "系统" if required is None else f"{required}级"
        lines.append(
            f"{index:02d}. {status} {item['key']} - {item['name']}｜{permission}"
        )
    if get_event_permission_level(event) >= 2 or is_admin_user(event.get_user_id()):
        group_suffix = " [群号]" if is_admin_user(event.get_user_id()) else ""
        lines.extend(
            [
                "=" * 22,
                f"用法：/关闭 序号{group_suffix} 或 /关闭功能 功能名{group_suffix}",
                f"用法：/开启 序号{group_suffix} 或 /开启功能 功能名{group_suffix}",
            ]
        )
    else:
        lines.extend(["=" * 22, "此级只可阅卷，不可改动开关。"])
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
async def handle_feature_list(event: MessageEvent, args: Message = CommandArg()):
    try:
        requested_group_id = _parse_optional_group_id(args.extract_plain_text())
        group_id = _resolve_group_command_target(event, requested_group_id)
    except PermissionError:
        await feature_list.finish("（按住总册）跨群翻账只交系统掌柜。")
    except ValueError:
        await feature_list.finish("（拨正算盘）用法：/功能列表 [群号]")
    await _require_group_admin(feature_list, event)
    audit_suffix = ""
    if requested_group_id is not None:
        audit_suffix = _audit_action(
            event,
            action="feature_list_view",
            scope="group",
            target_group_id=group_id,
            details={"command": "功能列表"},
        )
    await feature_list.finish(_render_feature_list_for_event(event, group_id) + audit_suffix)


enable_feature = on_command("开启功能", aliases={"开启"}, priority=3, block=True)


@enable_feature.handle()
async def handle_enable_feature(event: MessageEvent, args: Message = CommandArg()):
    try:
        target, requested_group_id = _parse_feature_toggle_args(
            args.extract_plain_text()
        )
        group_id = _resolve_group_command_target(event, requested_group_id)
    except PermissionError:
        await enable_feature.finish("（按住总册）跨群开门只交系统掌柜。")
    except ValueError:
        await enable_feature.finish("（拨正算盘）用法：/开启功能 功能名 [群号]")
    await _require_group_admin(enable_feature, event)
    if not has_command_permission(event, "feature_toggle"):
        await enable_feature.finish("（按住账页）阁下当前只可阅卷，尚不能改动开关。")
    feature = _resolve_feature_for_event(event, target, group_id)
    if not feature:
        await enable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    before = is_feature_enabled(feature, group_id)
    set_feature_enabled(feature, True, group_id)
    audit_suffix = _audit_action(
        event,
        action="feature_toggle",
        scope="group",
        target_group_id=group_id,
        details={"command": "开启功能", "feature_key": feature, "before": before, "after": True},
    )
    await enable_feature.finish(
        f"（群 {group_id} 账页落墨）已开启：{feature} - {get_feature_name(feature)}{audit_suffix}"
    )


disable_feature = on_command("关闭功能", aliases={"关闭"}, priority=3, block=True)


@disable_feature.handle()
async def handle_disable_feature(event: MessageEvent, args: Message = CommandArg()):
    try:
        target, requested_group_id = _parse_feature_toggle_args(
            args.extract_plain_text()
        )
        group_id = _resolve_group_command_target(event, requested_group_id)
    except PermissionError:
        await disable_feature.finish("（按住总册）跨群收门只交系统掌柜。")
    except ValueError:
        await disable_feature.finish("（拨正算盘）用法：/关闭功能 功能名 [群号]")
    await _require_group_admin(disable_feature, event)
    if not has_command_permission(event, "feature_toggle"):
        await disable_feature.finish("（按住账页）阁下当前只可阅卷，尚不能改动开关。")
    feature = _resolve_feature_for_event(event, target, group_id)
    if not feature:
        await disable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    before = is_feature_enabled(feature, group_id)
    try:
        set_feature_enabled(feature, False, group_id)
    except ValueError:
        await disable_feature.finish("（按住账本）管理员控制台不能关闭，否则就没人能开门了。")

    audit_suffix = _audit_action(
        event,
        action="feature_toggle",
        scope="group",
        target_group_id=group_id,
        details={"command": "关闭功能", "feature_key": feature, "before": before, "after": False},
    )
    await disable_feature.finish(f"（群 {group_id} 账页收笔）已关闭：{feature} - {get_feature_name(feature)}{audit_suffix}")


global_enable_feature = on_command("全局开启功能", priority=3, block=True)
global_disable_feature = on_command("全局关闭功能", priority=3, block=True)
manage_admin = on_command("管理员", priority=3, block=True)


def _parse_admin_args(raw_text: str) -> tuple[str, str, int | None]:
    parts = raw_text.strip().split()
    if len(parts) not in {2, 3}:
        raise ValueError("invalid_admin_args")
    group_id = normalize_id(parts[0], "group_id")
    user_id = normalize_id(parts[1], "user_id")
    level = normalize_permission_level(parts[2]) if len(parts) == 3 else None
    return group_id, user_id, level


@manage_admin.handle()
async def handle_manage_admin(event: MessageEvent, args: Message = CommandArg()):
    await _require_admin(manage_admin, event)
    try:
        group_id, user_id, level = _parse_admin_args(args.extract_plain_text())
    except ValueError:
        await manage_admin.finish(
            "（拨正算盘）用法：/管理员 群号 QQ号 权限等级\n"
            "权限等级须为 0 至 5；省略等级可查询，0 为撤权。"
        )

    if is_admin_user(user_id):
        await manage_admin.finish(
            "（按住总册）系统掌柜只由环境符令定名，不受群中账页增删升降。"
        )

    if level is None:
        current_level = get_group_permission_level(group_id, user_id)
        audit_suffix = _audit_action(
            event,
            action="permission_view",
            scope="group",
            target_group_id=group_id,
            target_user_id=user_id,
            details={"command": "管理员", "permission_level": current_level},
        )
        if current_level == 0:
            await manage_admin.finish(f"（翻过账页）此人在该群尚无机器人管理权限。{audit_suffix}")
        await manage_admin.finish(
            f"（账页摊开）此人在该群为 {current_level} 级"
            f"「{PERMISSION_LEVEL_NAMES[current_level]}」。{audit_suffix}"
        )

    previous_level = get_group_permission_level(group_id, user_id)
    try:
        set_group_permission_level(group_id, user_id, level)
    except ValueError as exc:
        if str(exc) == "system_admin_immutable":
            await manage_admin.finish(
                "（按住总册）系统掌柜只由环境符令定名，不受群中账页增删升降。"
            )
        await manage_admin.finish("（合上错页）这道授权未能落笔，请核对群号、QQ号与等级。")

    audit_suffix = _audit_action(
        event,
        action="permission_update",
        scope="group",
        target_group_id=group_id,
        target_user_id=user_id,
        details={
            "command": "管理员",
            "previous_permission_level": previous_level,
            "permission_level": level,
        },
    )
    if level == 0:
        await manage_admin.finish(f"（账页收笔）已撤去此人在该群的机器人管理权限。{audit_suffix}")
    await manage_admin.finish(
        f"（总册落印）已授予此人在该群 {level} 级"
        f"「{PERMISSION_LEVEL_NAMES[level]}」权限。{audit_suffix}"
    )


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
    before = is_feature_enabled(feature)
    try:
        set_feature_enabled(feature, enabled)
    except ValueError:
        await matcher.finish("（按住总账）管理员控制台不能关闭，否则就没人能开门了。")
    action = "开启" if enabled else "关闭"
    audit_suffix = _audit_action(
        event,
        action="global_feature_toggle",
        scope="global",
        details={
            "command": f"全局{action}功能",
            "feature_key": feature,
            "before": before,
            "after": enabled,
            "cleared_group_overrides": True,
        },
    )
    await matcher.finish(
        f"（总账落印）已全局{action}：{feature} - {get_feature_name(feature)}；各群旧覆盖一并归零。{audit_suffix}"
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


def _parse_debug_amount_and_group(text: str) -> tuple[int, str | None] | None:
    numbers = re.findall(r"[-+]?\d+", text)
    if not numbers or len(numbers) > 2:
        return None
    amount = _parse_positive_amount(numbers[0])
    if amount is None:
        return None
    try:
        group_id = normalize_id(numbers[1], "group_id") if len(numbers) == 2 else None
    except ValueError:
        return None
    return amount, group_id


def _debug_usage() -> str:
    return (
        "（压低声音）debug 符令这样写：\n"
        "/debug 1 开关本猫应答\n"
        "/debug 2 @某人 数字 [群号] 添积分\n"
        "/debug 3 @某人 数字 [群号] 添魅力\n"
        "/debug 4 [群号] 开关六个历史小游戏"
    )


async def _require_group_debug(
    event: MessageEvent,
    requested_group_id: str | None = None,
) -> str:
    if requested_group_id is not None:
        return requested_group_id
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    await debug_cmd.finish("（合上暗账）私聊施令须在末尾写明群号。")
    return ""


async def _handle_debug_points(bot: Bot, event: MessageEvent, args: Message, rest: str) -> None:
    target_id = get_first_at_user_id(args)
    parsed = _parse_debug_amount_and_group(rest)
    if not target_id or parsed is None:
        await debug_cmd.finish("（拨算盘）用法：/debug 2 @某人 数字 [群号]")
    amount, requested_group_id = parsed
    group_id = await _require_group_debug(event, requested_group_id)

    before = get_points(target_id, group_id)["current"]
    record = add_points(target_id, group_id, amount)
    sync_user_titles(target_id, group_id, record)
    target_name = await get_nickname(bot, target_id, context="debug.points")
    audit_suffix = _audit_action(
        event,
        action="debug_points",
        scope="group",
        target_group_id=group_id,
        target_user_id=target_id,
        details={"command": "debug 2", "amount": amount, "before": before, "after": record["current"]},
    )
    await debug_cmd.finish(
        f"（拨动群 {group_id} 暗账）已为 {target_name} 添上 {amount} 积分。\n"
        f"当前积分：{record['current']}｜累计获得：{record['total']}{audit_suffix}"
    )


async def _handle_debug_charm(bot: Bot, event: MessageEvent, args: Message, rest: str) -> None:
    target_id = get_first_at_user_id(args)
    parsed = _parse_debug_amount_and_group(rest)
    if not target_id or parsed is None:
        await debug_cmd.finish("（拂开花册）用法：/debug 3 @某人 数字 [群号]")
    amount, requested_group_id = parsed
    group_id = await _require_group_debug(event, requested_group_id)

    before = get_charm(target_id, group_id)
    record = change_charm(target_id, group_id, amount)
    sync_user_titles(target_id, group_id, get_points(target_id, group_id))
    target_name = await get_nickname(bot, target_id, context="debug.charm")
    audit_suffix = _audit_action(
        event,
        action="debug_charm",
        scope="group",
        target_group_id=group_id,
        target_user_id=target_id,
        details={"command": "debug 3", "amount": amount, "before": before, "after": record["charm"]},
    )
    await debug_cmd.finish(
        f"（群 {group_id} 花册落墨）已为 {target_name} 添上 {amount} 魅力。\n"
        f"当前魅力：{record['charm']}{audit_suffix}"
    )


def _toggle_all_legacy_games(group_id: str | None = None) -> tuple[bool, str]:
    target_enabled = not all(
        get_legacy_game_enabled(feature, group_id=group_id)
        for feature in LEGACY_GAME_ORDER
    )
    for feature in LEGACY_GAME_ORDER:
        set_feature_enabled(feature, target_enabled, group_id)
    names = "、".join(get_feature_name(feature) for feature in LEGACY_GAME_ORDER)
    return target_enabled, names


@debug_cmd.handle()
async def handle_debug(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    await _require_admin(debug_cmd, event)
    action, rest = _split_debug_args(args.extract_plain_text())

    if action == "1":
        before = is_bot_enabled()
        enabled = toggle_bot_enabled()
        audit_suffix = _audit_action(
            event,
            action="bot_toggle",
            scope="system",
            details={"command": "debug 1", "before": before, "after": enabled},
        )
        if enabled:
            await debug_cmd.finish(f"（抖开唐装）本猫醒酒归来，诸令照常。{audit_suffix}")
        await debug_cmd.finish(f"（收起折扇）本猫暂且收声，除 /debug 外皆不应。{audit_suffix}")

    if action == "2":
        await _handle_debug_points(bot, event, args, rest)
        return

    if action == "3":
        await _handle_debug_charm(bot, event, args, rest)
        return

    if action == "4":
        try:
            group_id = _parse_optional_group_id(rest)
        except ValueError:
            await debug_cmd.finish("（拨正算盘）用法：/debug 4 [群号]")
        before_values = [get_legacy_game_enabled(feature, group_id=group_id) for feature in LEGACY_GAME_ORDER]
        before = "open" if all(before_values) else "closed" if not any(before_values) else "mixed"
        enabled, names = _toggle_all_legacy_games(group_id)
        status = "开启" if enabled else "关闭"
        scope = f"群 {group_id} 的" if group_id is not None else "全局"
        audit_suffix = _audit_action(
            event,
            action="legacy_games_toggle",
            scope="group" if group_id is not None else "global",
            target_group_id=group_id,
            details={"command": "debug 4", "before": before, "after": enabled},
        )
        await debug_cmd.finish(
            f"（翻开旧局）{scope}六个历史小游戏已全部{status}：{names}{audit_suffix}"
        )

    await debug_cmd.finish(_debug_usage())
