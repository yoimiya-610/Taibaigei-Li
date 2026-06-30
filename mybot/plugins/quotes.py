from datetime import datetime
from pathlib import Path
import random
from typing import Any

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.command_registry import is_known_command
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.json_store import load_json, mutate_json
from mybot.common.logger import get_plugin_logger
from mybot.common.user_utils import get_nickname
from mybot.plugins.points import get_points, refund_points, spend_points


HELP_ITEMS = (
    HelpItem("社交互动", "/入典 - 收录群友发言，50积分", 40),
    HelpItem("社交互动", "/观典 - 查看入典语录", 41),
    HelpItem("社交互动", "/翻典 - 随机翻阅语录", 42),
    HelpItem("社交互动", "/搜典 关键词 - 检索群友语录", 43),
)
COMMAND_ALIASES = ("入典", "观典", "翻典", "搜典")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "classics.json"
DEFAULT_DATA = {"groups": {}}
MAX_CONTENT_LENGTH = 800
MAX_MESSAGE_LENGTH = 1800
MAX_SEARCH_RESULTS = 10
QUOTE_OTHER_COST = 50
DAILY_RECORD_LIMIT = 10
MAX_RECENT_AGE_SECONDS = 24 * 60 * 60

logger = get_plugin_logger(__name__)


def _format_time(timestamp: int | float | None = None) -> str:
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _date_key(timestamp: int | float | None = None) -> str:
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def _get_group(data: dict, group_id: str) -> dict:
    groups = data.setdefault("groups", {})
    return groups.setdefault(group_id, {"recent": {}, "classics": {}})


def _extract_target_id(event: MessageEvent) -> str | None:
    for segment in event.message:
        if segment.type != "at":
            continue
        target = str(segment.data.get("qq") or "").strip()
        if target and target != "all":
            return target
    return None


def _sender_name(event: GroupMessageEvent) -> str:
    sender = getattr(event, "sender", None)
    return (
        str(getattr(sender, "card", "") or "")
        or str(getattr(sender, "nickname", "") or "")
        or event.get_user_id()
    )


def _message_content(event: MessageEvent) -> str:
    content = event.get_plaintext().strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH].rstrip() + "...（后略）"
    return content


def _is_recent_expired(recent: dict) -> bool:
    timestamp = recent.get("timestamp")
    if not timestamp:
        return False
    try:
        return datetime.now().timestamp() - float(timestamp) > MAX_RECENT_AGE_SECONDS
    except (TypeError, ValueError):
        return False


def _is_protected_content(content: str) -> bool:
    if not content.strip():
        return True
    return is_known_command(content)


def _should_cache_message(event: MessageEvent) -> bool:
    if not is_feature_enabled("quotes"):
        return False
    if not isinstance(event, GroupMessageEvent):
        return False

    content = _message_content(event)
    if not content:
        return False
    return not is_known_command(content)


def _make_recent_record(event: GroupMessageEvent) -> dict:
    return {
        "message_id": getattr(event, "message_id", None),
        "user_id": event.get_user_id(),
        "nickname": _sender_name(event),
        "content": _message_content(event),
        "timestamp": getattr(event, "time", None),
        "time": _format_time(getattr(event, "time", None)),
    }


def _get_recent(group_id: str, target_id: str) -> dict | None:
    data = load_json(DATA_FILE, DEFAULT_DATA)
    group = data.get("groups", {}).get(group_id, {})
    record = group.get("recent", {}).get(target_id)
    return dict(record) if isinstance(record, dict) else None


def _store_recent(group_id: str, target_id: str, record: dict) -> None:
    def mutator(data: dict) -> None:
        group = _get_group(data, group_id)
        group.setdefault("recent", {})[target_id] = record

    mutate_json(DATA_FILE, DEFAULT_DATA, mutator)


def _find_existing_classic(records: list[dict], recent: dict) -> dict | None:
    message_id = recent.get("message_id")
    for record in records:
        if message_id is not None and record.get("message_id") == message_id:
            return record
        if (
            record.get("content") == recent.get("content")
            and record.get("message_timestamp") == recent.get("timestamp")
        ):
            return record
    return None


def _count_today_records(group: dict, recorder_id: str, timestamp: int | float) -> int:
    today = _date_key(timestamp)
    total = 0
    for records in group.get("classics", {}).values():
        if not isinstance(records, list):
            continue
        for record in records:
            if record.get("recorder_id") != recorder_id:
                continue
            record_timestamp = record.get("recorded_timestamp")
            if record_timestamp and _date_key(record_timestamp) == today:
                total += 1
    return total


def _add_classic(
    group_id: str,
    target_id: str,
    target_name: str,
    recent: dict,
    recorder_id: str,
    recorder_name: str,
) -> tuple[str, dict, int]:
    now_timestamp = int(datetime.now().timestamp())
    new_record = {
        "message_id": recent.get("message_id"),
        "speaker_id": target_id,
        "speaker_name": target_name,
        "content": recent.get("content", ""),
        "message_time": recent.get("time") or _format_time(recent.get("timestamp")),
        "message_timestamp": recent.get("timestamp"),
        "recorded_at": _format_time(now_timestamp),
        "recorded_timestamp": now_timestamp,
        "recorder_id": recorder_id,
        "recorder_name": recorder_name,
    }

    def mutator(data: dict) -> tuple[str, dict, int]:
        group = _get_group(data, group_id)
        classics = group.setdefault("classics", {})
        records = classics.setdefault(target_id, [])
        existing = _find_existing_classic(records, recent)
        if existing:
            return "duplicate", existing, len(records)
        if _count_today_records(group, recorder_id, now_timestamp) >= DAILY_RECORD_LIMIT:
            return "daily_limit", {}, len(records)

        records.append(new_record)
        return "created", new_record, len(records)

    return mutate_json(DATA_FILE, DEFAULT_DATA, mutator)


def _get_classics(group_id: str, target_id: str) -> list[dict]:
    data = load_json(DATA_FILE, DEFAULT_DATA)
    group = data.get("groups", {}).get(group_id, {})
    records = group.get("classics", {}).get(target_id, [])
    return list(records) if isinstance(records, list) else []


def _get_all_classics(group_id: str) -> list[dict]:
    data = load_json(DATA_FILE, DEFAULT_DATA)
    group = data.get("groups", {}).get(group_id, {})
    classics = group.get("classics", {})
    records: list[dict] = []
    if not isinstance(classics, dict):
        return records

    for user_records in classics.values():
        if isinstance(user_records, list):
            records.extend(record for record in user_records if isinstance(record, dict))
    return records


def _quote_block(index: int, record: dict) -> str:
    return (
        f"{index}. {record.get('message_time', '未知时间')}\n"
        f"「{record.get('content', '')}」\n"
        f"入典：{record.get('recorded_at', '未知时间')}"
        f"｜执笔人：{record.get('recorder_name', record.get('recorder_id', '未知'))}"
    )


def _single_quote_text(record: dict) -> str:
    return (
        "📖 翻典一页 📖\n"
        "====================\n"
        f"人物：{record.get('speaker_name', record.get('speaker_id', '未知'))}\n"
        f"时间：{record.get('message_time', '未知时间')}\n"
        f"内容：\n「{record.get('content', '')}」\n"
        "====================\n"
        f"入典：{record.get('recorded_at', '未知时间')}\n"
        f"执笔人：{record.get('recorder_name', record.get('recorder_id', '未知'))}\n"
        "『旧卷偶然翻一页，笑声又上酒杯来。』"
    )


def _trim_text(text: str, limit: int = 80) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 1)].rstrip() + "…"


def _search_classics(records: list[dict], keyword: str, limit: int = MAX_SEARCH_RESULTS) -> list[dict]:
    term = keyword.strip().lower()
    if not term:
        return []

    matches = [
        record
        for record in records
        if term in str(record.get("content", "")).lower()
    ]
    matches.sort(key=lambda record: record.get("recorded_timestamp") or 0, reverse=True)
    return matches[:limit]


def _search_result_block(index: int, record: dict) -> str:
    speaker = record.get("speaker_name", record.get("speaker_id", "未知"))
    content = _trim_text(record.get("content", ""))
    return (
        f"{index}. {speaker}｜{record.get('message_time', '未知时间')}\n"
        f"「{content}」\n"
        f"入典：{record.get('recorded_at', '未知时间')}"
    )


def _split_long_text(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        extra = len(line) + 1
        if current and current_len + extra > MAX_MESSAGE_LENGTH:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += extra

    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


async def _send_long(matcher: Any, text: str) -> None:
    chunks = _split_long_text(text)
    for chunk in chunks[:-1]:
        await matcher.send(chunk)
    await matcher.finish(chunks[-1])


quote_message_cache = on_message(rule=Rule(_should_cache_message), priority=100, block=False)
add_quote = on_command("入典", priority=5, block=True)
view_quotes = on_command("观典", priority=5, block=True)
random_quote = on_command("翻典", priority=5, block=True)
search_quotes = on_command("搜典", priority=5, block=True)


@quote_message_cache.handle()
async def handle_quote_message_cache(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    try:
        _store_recent(str(event.group_id), event.get_user_id(), _make_recent_record(event))
    except Exception as exc:
        logger.exception(f"记录最近群消息失败 group_id={event.group_id} user_id={event.get_user_id()}: {exc}")


@add_quote.handle()
async def handle_add_quote(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await add_quote.finish("（合上册子）语录本要在群里写才有味道。")

    group_id = str(event.group_id)
    target_id = _extract_target_id(event)
    if not target_id:
        await add_quote.finish(
            "📖 群友语录本 📖\n"
            "====================\n"
            "用法：/入典 @某人\n"
            "收录自己免费，收录他人花费 50 积分。\n"
            "（蘸墨）本猫会收录此人在本群最近一句有效发言。\n"
            "『一言若值得流传，便请诸君替它落款。』"
        )

    recent = _get_recent(group_id, target_id)
    if not recent:
        target_name = await get_nickname(bot, target_id, context="入典.target")
        await add_quote.finish(f"（翻空白页）还没记到 {target_name} 最近说过什么。")

    if target_id == str(getattr(event, "self_id", "")):
        await add_quote.finish("（按住笔）本猫自己的话不入群友典。")

    if _is_recent_expired(recent):
        target_name = await get_nickname(bot, target_id, context="入典.target")
        await add_quote.finish(f"（吹落灰尘）{target_name} 最近一句已经过了 24 小时，旧墨不入新典。")

    content = str(recent.get("content", "")).strip()
    if _is_protected_content(content):
        await add_quote.finish("（合上册子）这句不适合入典，换一句更有灵魂的。")

    target_name = str(recent.get("nickname") or await get_nickname(bot, target_id, context="入典.target"))
    recorder_id = event.get_user_id()
    recorder_name = await get_nickname(bot, recorder_id, context="入典.recorder")
    cost = QUOTE_OTHER_COST if target_id != recorder_id else 0

    if cost:
        points = get_points(recorder_id, group_id)
        if points["current"] < cost:
            await add_quote.finish(
                f"（拨算盘）入典他人语录需 {cost} 积分，阁下当前只有 {points['current']} 积分。"
            )
        if not spend_points(recorder_id, group_id, cost):
            await add_quote.finish("（扶额）扣除积分失败，稍后再试。")

    try:
        status, record, count = _add_classic(
            group_id,
            target_id,
            target_name,
            recent,
            recorder_id,
            recorder_name,
        )
    except Exception as exc:
        if cost:
            refund_points(recorder_id, group_id, cost)
        logger.exception(f"入典写入失败 group_id={group_id} target_id={target_id}: {exc}")
        await add_quote.finish("（墨洒账本）入典失败，本次积分已退回。")

    if status == "duplicate":
        if cost:
            refund_points(recorder_id, group_id, cost)
        await add_quote.finish(
            f"（敲敲册页）这句已经入过典了。\n"
            f"====================\n"
            f"{target_name} 第 {count} 条：\n"
            f"「{record.get('content', '')}」"
        )
    if status == "daily_limit":
        if cost:
            refund_points(recorder_id, group_id, cost)
        await add_quote.finish(f"（合上册子）今日最多入典 {DAILY_RECORD_LIMIT} 次，明日再来添墨。")

    cost_text = f"{cost} 积分" if cost else "0 积分（收录本人语录）"
    await add_quote.finish(
        f"📖 入典成功 📖\n"
        f"====================\n"
        f"人物：{target_name}\n"
        f"时间：{record['message_time']}\n"
        f"内容：\n「{record['content']}」\n"
        f"====================\n"
        f"花费：{cost_text}\n"
        f"当前共 {count} 条。\n"
        f"『一言落纸成风月，群中从此有典章。』"
    )


@view_quotes.handle()
async def handle_view_quotes(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await view_quotes.finish("（合上册子）语录本要在群里看才对味。")

    group_id = str(event.group_id)
    target_id = _extract_target_id(event)
    if not target_id:
        await view_quotes.finish(
            "📖 群友语录本 📖\n"
            "====================\n"
            "用法：/观典 @某人\n"
            "（翻册）本猫会列出此人在本群所有入典语录。\n"
            "『旧言藏在新书页，翻到当时又一笑。』"
        )

    target_name = await get_nickname(bot, target_id, context="观典.target")
    records = _get_classics(group_id, target_id)
    if not records:
        await view_quotes.finish(f"（翻到白页）{target_name} 暂无入典语录。")

    lines = [
        "📖 李太白给·群友语录本 📖",
        "=" * 22,
        f"{target_name} 共入典 {len(records)} 条",
        "=" * 22,
    ]
    for index, record in enumerate(records, 1):
        lines.append(_quote_block(index, record))
        if index != len(records):
            lines.append("-" * 22)

    lines.extend(
        [
            "=" * 22,
            "『片言只语皆可藏，群中旧事自流芳。』",
        ]
    )
    await _send_long(view_quotes, "\n".join(lines))


@random_quote.handle()
async def handle_random_quote(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await random_quote.finish("（合上册子）翻典要在群里翻才有声响。")

    group_id = str(event.group_id)
    target_id = _extract_target_id(event)
    if target_id:
        target_name = await get_nickname(bot, target_id, context="翻典.target")
        records = _get_classics(group_id, target_id)
        if not records:
            await random_quote.finish(f"（翻到白页）{target_name} 暂无入典语录。")
    else:
        records = _get_all_classics(group_id)
        if not records:
            await random_quote.finish("（翻到白页）本群还没有入典语录。")

    await random_quote.finish(_single_quote_text(random.choice(records)))


@search_quotes.handle()
async def handle_search_quotes(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await search_quotes.finish("（合上册子）搜典要在群里翻才有旧声回响。")

    group_id = str(event.group_id)
    target_id = _extract_target_id(event)
    keyword = args.extract_plain_text().strip()
    if not keyword:
        await search_quotes.finish(
            "📖 群友语录检索 📖\n"
            "====================\n"
            "用法：/搜典 关键词\n"
            "或：/搜典 @某人 关键词\n"
            "（拂开旧页）本猫会按关键字翻找本群入典语录。\n"
            "『旧句若藏烟火气，一搜便有故人声。』"
        )

    if target_id:
        target_name = await get_nickname(bot, target_id, context="搜典.target")
        records = _get_classics(group_id, target_id)
        if not records:
            await search_quotes.finish(f"（翻到白页）{target_name} 暂无入典语录。")
    else:
        target_name = "本群"
        records = _get_all_classics(group_id)
        if not records:
            await search_quotes.finish("（翻到白页）本群还没有入典语录。")

    matches = _search_classics(records, keyword)
    if not matches:
        await search_quotes.finish(
            f"（指尖停在旧页间）{target_name} 语录里还没搜到“{keyword}”。\n"
            "『欲寻旧句暂无迹，且待来时再落章。』"
        )

    lines = [
        "📖 李太白给·搜典结果 📖",
        "=" * 22,
        f"范围：{target_name}",
        f"关键词：{keyword}",
        f"命中：{len(matches)} 条（最多展示 {MAX_SEARCH_RESULTS} 条）",
        "=" * 22,
    ]
    for index, record in enumerate(matches, 1):
        lines.append(_search_result_block(index, record))
        if index != len(matches):
            lines.append("-" * 22)

    lines.extend(
        [
            "=" * 22,
            "『卷中旧语经风久，翻到相逢又似新。』",
        ]
    )
    await _send_long(search_quotes, "\n".join(lines))
