from mybot.common.plugin_metadata import declare_plugin


PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="command_finder",
    name="寻令路引",
    default_enabled=True,
    scope="group",
    permission_level=2,
    privacy_level="public",
    backup_policy="none",
)

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.command_discovery import (
    extract_explicit_command,
    is_registered_explicit_command,
    search_public_commands,
    suggest_public_commands,
)
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.message_utils import get_message_text


HELP_ITEMS = (
    HelpItem("系统说明", "/寻令 关键词 - 搜索命令与玩法", 40),
)
COMMAND_ALIASES = ("寻令",)

MAX_KEYWORD_LENGTH = 40


def _event_group_id(event: MessageEvent) -> str | None:
    return str(event.group_id) if isinstance(event, GroupMessageEvent) else None


def _render_search(keyword: str, event: MessageEvent) -> str:
    normalized = keyword.strip()
    if not normalized:
        return (
            "（摊开路引）要寻哪道令，先递个关键词给本猫。\n"
            "用法：/寻令 关键词\n"
            "例：/寻令 签到、/寻令 猜拳、/寻令 玩法\n"
            "『半卷藏门径，一词引路来。』"
        )
    if len(normalized) > MAX_KEYWORD_LENGTH:
        return (
            "（按住铺满案头的长卷）关键词写得短些，本猫才好替你翻。\n"
            f"请控制在 {MAX_KEYWORD_LENGTH} 个字以内。\n"
            "『一词点破卷中路，何必千言压案来。』"
        )

    results = search_public_commands(
        normalized,
        group_id=_event_group_id(event),
        user_id=event.get_user_id(),
    )
    if not results:
        return (
            f"（翻到卷尾）没寻到与“{normalized}”相合的明面入口。\n"
            "换个更短的词再试，或用 /命令全览 看整卷。\n"
            "『词若未逢卷上字，换支小令再来寻。』"
        )

    lines = [
        "🧭 李太白给·寻令 🧭",
        "=" * 22,
        f"（推推墨镜）“{normalized}”寻得这些入口：",
        "=" * 22,
    ]
    for index, result in enumerate(results, start=1):
        suffix = "（兼容入口）" if result.kind == "alias" else ""
        lines.append(f"{index}. {result.text}{suffix}")
    lines.extend(
        [
            "=" * 22,
            "可直接照着入口试试；想看整卷可用 /命令全览。",
            "『一词牵出千般路，照着门牌便可行。』",
        ]
    )
    return "\n".join(lines)


def _should_suggest_unknown(event: MessageEvent) -> bool:
    group_id = _event_group_id(event)
    if not is_feature_enabled("command_finder", group_id):
        return False
    message = get_message_text(event)
    return (
        extract_explicit_command(message) is not None
        and not is_registered_explicit_command(message)
    )


def _render_unknown_command(command: str, event: MessageEvent) -> str:
    search_term = command.strip()[:MAX_KEYWORD_LENGTH]
    display_command = search_term + ("…" if len(command.strip()) > MAX_KEYWORD_LENGTH else "")
    suggestions = suggest_public_commands(
        search_term,
        group_id=_event_group_id(event),
        user_id=event.get_user_id(),
    )
    lines = [f"（扶正墨镜）“/{display_command}”这道令像是写岔了一笔。"]
    if suggestions:
        lines.append(f"最接近的入口：{'、'.join(suggestions)}")
    else:
        lines.append(f"可试试 /寻令 {search_term}，或用 /帮助 翻总卷。")
    lines.append("『一字若教风吹偏，循着近路也能还。』")
    return "\n".join(lines)


command_search = on_command("寻令", priority=5, block=True)


@command_search.handle()
async def handle_command_search(event: MessageEvent, args: Message = CommandArg()):
    await command_search.finish(_render_search(args.extract_plain_text(), event))


unknown_command = on_message(
    rule=Rule(_should_suggest_unknown),
    priority=97,
    block=True,
)


@unknown_command.handle()
async def handle_unknown_command(event: MessageEvent):
    command = extract_explicit_command(get_message_text(event))
    if command:
        await unknown_command.finish(_render_unknown_command(command, event))
