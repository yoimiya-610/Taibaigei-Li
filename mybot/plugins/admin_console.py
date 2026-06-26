from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from common.admin import get_admin_user_ids, is_admin_user
from common.feature_flags import (
    collect_features,
    find_disabled_feature_for_message,
    get_feature_name,
    resolve_feature,
    set_feature_enabled,
)
from common.help_registry import HelpItem
from common.message_utils import get_message_text


HELP_ITEMS = (
    HelpItem("系统说明", "/功能列表 - 查看功能开关", 20),
)
COMMAND_ALIASES = (
    "功能列表",
    "功能状态",
    "开启功能",
    "关闭功能",
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


def _render_feature_list() -> str:
    lines = [
        "🛠 李太白给·功能开关 🛠",
        "=" * 22,
        "（翻账本）当前功能如下：",
        "=" * 22,
    ]

    for item in collect_features():
        status = "开" if item["enabled"] else "关"
        locked = " / 保护" if item["protected"] else ""
        aliases = "、".join(item["aliases"][:4])
        alias_text = f"｜{aliases}" if aliases else ""
        lines.append(f"{status} {item['key']} - {item['name']}{locked}{alias_text}")

    lines.extend(
        [
            "=" * 22,
            "用法：/关闭功能 功能名",
            "用法：/开启功能 功能名",
        ]
    )
    return "\n".join(lines)


def disabled_feature_rule(event: MessageEvent) -> bool:
    return find_disabled_feature_for_message(get_message_text(event)) is not None


feature_guard = on_message(rule=Rule(disabled_feature_rule), priority=0, block=True)


@feature_guard.handle()
async def handle_disabled_feature(event: MessageEvent):
    feature = find_disabled_feature_for_message(get_message_text(event))
    feature_name = get_feature_name(feature) if feature else "该功能"
    await feature_guard.finish(
        f"（合上折扇）{feature_name} 暂时歇业中。\n"
        f"如需开启，请让管理员使用 /开启功能 {feature or ''}"
    )


feature_list = on_command("功能列表", aliases={"功能状态"}, priority=3, block=True)


@feature_list.handle()
async def handle_feature_list(event: MessageEvent):
    await _require_admin(feature_list, event)
    await feature_list.finish(_render_feature_list())


enable_feature = on_command("开启功能", priority=3, block=True)


@enable_feature.handle()
async def handle_enable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _require_admin(enable_feature, event)
    target = args.extract_plain_text().strip()
    feature = resolve_feature(target)
    if not feature:
        await enable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    set_feature_enabled(feature, True)
    await enable_feature.finish(f"（点头）已开启：{feature} - {get_feature_name(feature)}")


disable_feature = on_command("关闭功能", priority=3, block=True)


@disable_feature.handle()
async def handle_disable_feature(event: MessageEvent, args: Message = CommandArg()):
    await _require_admin(disable_feature, event)
    target = args.extract_plain_text().strip()
    feature = resolve_feature(target)
    if not feature:
        await disable_feature.finish("（翻账本）没找到这个功能名。输入 /功能列表 看看。")

    try:
        set_feature_enabled(feature, False)
    except ValueError:
        await disable_feature.finish("（按住账本）管理员控制台不能关闭，否则就没人能开门了。")

    await disable_feature.finish(f"（收起折扇）已关闭：{feature} - {get_feature_name(feature)}")
