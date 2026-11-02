from __future__ import annotations

from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="image_library",
    name="群聊图片库",
    default_enabled=False,
    scope="group",
    permission_level=5,
    data_files=("data/image_library",),
    privacy_level="sensitive",
    backup_policy="optional",
)

import random
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

from mybot.common.admin import get_event_permission_level
from mybot.common.config import get_image_library_settings
from mybot.common.help_registry import HelpItem
from mybot.common.image_library import (
    ImageDownloadError,
    ImageLibraryError,
    ImageNotFoundError,
    ImagePermissionError,
    ImageQuotaError,
    ImageTooLargeError,
    InvalidImageError,
    add_image_tags,
    delete_image,
    download_image,
    get_library_stats,
    list_images,
    normalize_tags,
    read_image_bytes,
    read_local_image,
    remove_image_tags,
    search_images,
    store_image,
)
from mybot.common.logger import get_plugin_logger
from mybot.common.message_utils import get_reply_message_id
from mybot.common.onebot_capabilities import Capability, call_capability_api
from mybot.common.usage_policy import consume_quota, quota_records, scaled_quota_plan


HELP_ITEMS = (
    HelpItem("趣味功能", "/图片库 - 收藏、检索与整理本群图片", 6),
)
COMMAND_ALIASES = (
    "图片库",
    "图册",
    "收图",
    "找图",
    "随机图",
    "删图",
    "加标签",
    "添加标签",
    "删标签",
    "删除标签",
)
PUBLIC_COMMANDS = COMMAND_ALIASES

logger = get_plugin_logger(__name__)
IMAGE_RATE_WINDOW_SECONDS = 60
IMAGE_COLLECT_RATE_LIMIT = 5
IMAGE_SEND_RATE_LIMIT = 10
IMAGE_TAG_RATE_LIMIT = 10
# 兼容既有测试清理入口；记录由共享配额策略统一维护。
_image_rate_records = quota_records

image_library_help = on_command("图片库", aliases={"图册"}, priority=5, block=True)
collect_image = on_command("收图", priority=5, block=True)
find_image = on_command("找图", priority=5, block=True)
random_image = on_command("随机图", priority=5, block=True)
remove_image = on_command("删图", priority=5, block=True)
add_tags = on_command("加标签", aliases={"添加标签"}, priority=5, block=True)
remove_tags = on_command("删标签", aliases={"删除标签"}, priority=5, block=True)


class ImageSourceError(RuntimeError):
    pass


def _consume_image_rate(
    group_id: str,
    user_id: str,
    action: str,
    limit: int,
    *,
    now: float | None = None,
) -> int:
    decision = consume_quota(
        f"image_library:{action}",
        str(user_id),
        str(group_id),
        scaled_quota_plan(limit, IMAGE_RATE_WINDOW_SECONDS),
        now=now,
    )
    return 0 if decision.allowed else decision.wait_seconds


def _format_size(size_bytes: int) -> str:
    value = float(max(0, size_bytes))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def _parse_tag_edit_args(value: str) -> tuple[int, list[str]]:
    parts = value.strip().split(maxsplit=1)
    identifier = parts[0].lstrip("#") if parts else ""
    if not identifier.isdigit() or int(identifier) <= 0:
        raise ValueError("invalid_image_id")
    tags = normalize_tags(parts[1] if len(parts) > 1 else "")
    if not tags:
        raise ValueError("missing_image_tags")
    return int(identifier), tags


def _format_record_tags(record: dict[str, Any]) -> str:
    return "、".join(str(tag) for tag in record.get("tags", [])) or "未分类"


def _extract_image_segments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, MessageSegment):
        return [dict(value.data)] if value.type == "image" else []
    if isinstance(value, Message):
        images: list[dict[str, Any]] = []
        for segment in value:
            images.extend(_extract_image_segments(segment))
        return images
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("data"), dict):
            return [dict(value["data"])]
        images = []
        for key in ("message", "raw_message", "original_message", "data"):
            child = value.get(key)
            if isinstance(child, (dict, list, tuple, Message, MessageSegment)):
                images.extend(_extract_image_segments(child))
        return images
    if isinstance(value, (list, tuple)):
        images = []
        for item in value:
            images.extend(_extract_image_segments(item))
        return images
    return []


def _extract_sender_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    sender = value.get("sender")
    if isinstance(sender, dict) and sender.get("user_id") is not None:
        return str(sender["user_id"])
    if value.get("user_id") is not None:
        return str(value["user_id"])
    data = value.get("data")
    return _extract_sender_id(data) if isinstance(data, dict) else None


def _api_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("data")
    if isinstance(nested, dict) and any(
        key in nested for key in ("file", "file_id", "path", "url", "texts")
    ):
        return dict(nested)
    return dict(value)


async def _resolve_source_image(
    bot: Bot,
    event: GroupMessageEvent,
) -> tuple[dict[str, Any], str, str]:
    direct_images = _extract_image_segments(event.message)
    if len(direct_images) > 1:
        raise ImageSourceError("multiple_images")
    if direct_images:
        return direct_images[0], event.get_user_id(), str(event.message_id)

    reply_id = get_reply_message_id(event)
    if not reply_id:
        raise ImageSourceError("missing_image")
    try:
        reply_message = await bot.get_msg(message_id=reply_id)
    except Exception as exc:
        logger.warning(
            "回复图片读取失败 group_id=%s message_id=%s error=%s",
            event.group_id,
            reply_id,
            exc,
        )
        raise ImageSourceError("reply_unavailable") from exc
    reply_images = _extract_image_segments(reply_message)
    if not reply_images:
        raise ImageSourceError("reply_has_no_image")
    if len(reply_images) > 1:
        raise ImageSourceError("multiple_images")
    return (
        reply_images[0],
        _extract_sender_id(reply_message) or event.get_user_id(),
        reply_id,
    )


async def _refresh_image_data(bot: Bot, image_data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(image_data)
    reference = merged.get("file_id") or merged.get("file")
    if not reference:
        return merged
    merged["_ocr_reference"] = str(reference)
    try:
        refreshed = _api_data(
            await call_capability_api(
                bot,
                Capability.IMAGE_REFRESH,
                "get_image",
                file=str(reference),
            )
        )
    except Exception as exc:
        logger.warning("图片地址刷新能力不可用，尝试使用消息原值：%s", exc)
        return merged
    for key, value in refreshed.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


async def _load_source_bytes(
    image_data: dict[str, Any],
    *,
    max_file_bytes: int,
) -> bytes:
    url = str(image_data.get("url") or "").strip()
    download_error: Exception | None = None
    if url:
        try:
            return await download_image(url, max_file_bytes=max_file_bytes)
        except ImageLibraryError as exc:
            download_error = exc

    for key in ("path", "file"):
        path_value = str(image_data.get(key) or "").strip()
        if not path_value:
            continue
        try:
            return read_local_image(path_value, max_file_bytes=max_file_bytes)
        except ImageLibraryError as exc:
            download_error = download_error or exc

    raise ImageDownloadError("image_source_unavailable") from download_error


def _extract_ocr_text(value: Any) -> str:
    data = _api_data(value)
    texts = data.get("texts", [])
    if not isinstance(texts, list):
        return ""
    return "\n".join(
        str(item.get("text", "")).strip()
        for item in texts
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )


async def _read_ocr(bot: Bot, image_data: dict[str, Any]) -> str:
    reference = (
        image_data.get("_ocr_reference")
        or image_data.get("file_id")
        or image_data.get("file")
    )
    if not reference:
        return ""
    try:
        result = await call_capability_api(
            bot,
            Capability.IMAGE_OCR,
            "ocr_image",
            image=str(reference),
        )
    except Exception as exc:
        logger.info("图片 OCR 能力不可用，本次仅按标签入库：%s", exc)
        return ""
    return _extract_ocr_text(result)


def _record_caption(record: dict[str, Any], action: str) -> str:
    tags = _format_record_tags(record)
    return (
        f"🖼 李太白给·{action}\n"
        f"图号：#{record.get('id')}｜标签：{tags}\n"
        f"收录：{record.get('saved_at', '未知时间')}"
    )


def _render_image_library_help(settings, stats: dict[str, Any]) -> str:
    top_tags = "、".join(f"{tag}({count})" for tag, count in stats["top_tags"]) or "暂无"
    ocr_status = "开" if settings.ocr_enabled else "关"
    return (
        "🖼 李太白给·群聊图片库 🖼\n"
        "====================\n"
        f"本群藏图：{stats['count']} 张 / {settings.max_group_images} 张\n"
        f"占用：{_format_size(stats['size_bytes'])} / {_format_size(settings.max_group_bytes)}\n"
        f"常用标签：{top_tags}\n"
        f"文字识别：{ocr_status}\n"
        "====================\n"
        "回复图片：/收图 标签1 标签2\n"
        "附带图片：/收图 标签1 标签2\n"
        "检索发送：/找图 关键词\n"
        "随机翻图：/随机图 [关键词]\n"
        "添加标签：/加标签 图号 标签1 标签2\n"
        "删除标签：/删标签 图号 标签1 标签2\n"
        "删除藏图：/删图 图号\n"
        "『画入匣中留旧影，词从卷里唤相逢。』"
    )


async def _finish_with_record(
    matcher,
    group_id: str,
    record: dict[str, Any],
    action: str,
) -> None:
    settings = get_image_library_settings()
    content = read_image_bytes(
        group_id,
        record,
        max_file_bytes=settings.max_file_bytes,
    )
    await matcher.finish(
        Message(
            [
                MessageSegment.text(_record_caption(record, action) + "\n"),
                MessageSegment.image(content),
            ]
        )
    )


@image_library_help.handle()
async def handle_image_library_help(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await image_library_help.finish("（合上画匣）图片库只在对应群中开卷。")
    settings = get_image_library_settings()
    stats = get_library_stats(str(event.group_id))
    await image_library_help.finish(_render_image_library_help(settings, stats))


@collect_image.handle()
async def handle_collect_image(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
):
    if not isinstance(event, GroupMessageEvent):
        await collect_image.finish("（抱紧画匣）收图须在对应群中落款。")
    wait_seconds = _consume_image_rate(
        str(event.group_id),
        event.get_user_id(),
        "collect",
        IMAGE_COLLECT_RATE_LIMIT,
    )
    if wait_seconds:
        await collect_image.finish(f"（按住画匣）收图太密了，且等 {wait_seconds} 秒再落签。")

    try:
        tags = normalize_tags(args.extract_plain_text())
    except ValueError as exc:
        if str(exc) == "too_many_image_tags":
            await collect_image.finish("（墨签散了一桌）一次最多写八个标签。")
        await collect_image.finish("（拈起标签）标签过长或含有怪字，换个短些的名字吧。")
    if not tags:
        await collect_image.finish(
            "（递来空白墨签）请先写标签，例如：回复图片后发送 /收图 猫猫 开心。"
        )

    settings = get_image_library_settings()
    try:
        image_data, source_user_id, source_message_id = await _resolve_source_image(
            bot,
            event,
        )
        image_data = await _refresh_image_data(bot, image_data)
        content = await _load_source_bytes(
            image_data,
            max_file_bytes=settings.max_file_bytes,
        )
        ocr_text = await _read_ocr(bot, image_data) if settings.ocr_enabled else ""
        result = store_image(
            str(event.group_id),
            content,
            tags=tags,
            saved_by=event.get_user_id(),
            source_user_id=source_user_id,
            source_message_id=source_message_id,
            ocr_text=ocr_text,
            summary=str(image_data.get("summary") or ""),
            max_file_bytes=settings.max_file_bytes,
            max_group_bytes=settings.max_group_bytes,
            max_group_images=settings.max_group_images,
        )
    except ImageSourceError as exc:
        messages = {
            "missing_image": "（画匣空空）请附上一张图，或回复一张图后再用 /收图 标签。",
            "reply_unavailable": "（循着旧墨翻卷）那条回复已取不到了，请直接附图再试。",
            "reply_has_no_image": "（敲敲旧卷）回复里没有可收的图片。",
            "multiple_images": "（画卷铺得太满）一次只收一张图，请分开落签。",
        }
        await collect_image.finish(messages.get(str(exc), "（合上画匣）这张图暂时取不到。"))
    except ImageTooLargeError:
        await collect_image.finish(
            f"（双手托不住画卷）单图最多 {_format_size(settings.max_file_bytes)}，请换张轻些的。"
        )
    except InvalidImageError:
        await collect_image.finish("（辨了辨纸墨）暂只收 JPG、PNG、GIF、WebP 与 BMP 图片。")
    except ImageQuotaError:
        await collect_image.finish("（画匣已经合不上）本群图片库已到容量上限，请先清理旧图。")
    except (ImageDownloadError, ImageLibraryError) as exc:
        logger.exception(
            "图片入库失败 group_id=%s user_id=%s error=%s",
            event.group_id,
            event.get_user_id(),
            exc,
        )
        await collect_image.finish("（画卷在风里散了）这张图没能妥善收入匣中，稍后再试。")

    if result.status == "duplicate":
        await collect_image.finish(
            f"（敲敲画匣）这幅画早已入卷，图号是 #{result.record.get('id')}。"
        )
    ocr_notice = "，并抄下了图中文字" if result.record.get("ocr_text") else ""
    await collect_image.finish(
        f"（贴好墨签）图片已收入本群画匣，图号 #{result.record.get('id')}{ocr_notice}。\n"
        f"标签：{'、'.join(result.record.get('tags', []))}\n"
        "『一幅新图藏袖底，他时循字便相逢。』"
    )


@find_image.handle()
async def handle_find_image(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await find_image.finish("（合上画匣）找图须在原群的画卷里寻。")
    wait_seconds = _consume_image_rate(
        str(event.group_id),
        event.get_user_id(),
        "send",
        IMAGE_SEND_RATE_LIMIT,
    )
    if wait_seconds:
        await find_image.finish(f"（按住翻卷的手）找图太快了，且等 {wait_seconds} 秒。")
    query = args.extract_plain_text().strip()
    if not query:
        await find_image.finish("（提笔等题）用法：/找图 关键词。")
    try:
        matches = search_images(str(event.group_id), query, limit=10)
    except ValueError:
        await find_image.finish("（墨签太长）关键词请控制在八个短词以内。")
    if not matches:
        await find_image.finish(
            f"（翻遍画匣）本群还没找到与“{query[:60]}”相合的图。\n"
            "『欲寻旧影无踪处，且待新图入卷来。』"
        )
    try:
        await _finish_with_record(find_image, str(event.group_id), matches[0], "寻图一幅")
    except ImageLibraryError as exc:
        logger.exception("图片读取失败 group_id=%s image_id=%s error=%s", event.group_id, matches[0].get("id"), exc)
        await find_image.finish("（画卷只余空页）这张图的原文件已缺失，请掌柜清理记录。")


@random_image.handle()
async def handle_random_image(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await random_image.finish("（合上画匣）翻图须在原群的画卷里寻。")
    wait_seconds = _consume_image_rate(
        str(event.group_id),
        event.get_user_id(),
        "send",
        IMAGE_SEND_RATE_LIMIT,
    )
    if wait_seconds:
        await random_image.finish(f"（按住翻卷的手）翻图太快了，且等 {wait_seconds} 秒。")
    query = args.extract_plain_text().strip()
    try:
        candidates = (
            search_images(str(event.group_id), query, limit=100)
            if query
            else list_images(str(event.group_id))
        )
    except ValueError:
        await random_image.finish("（墨签太长）关键词请控制在八个短词以内。")
    if not candidates:
        await random_image.finish("（抖了抖空画匣）本群还没有可翻的图片。")
    record = random.choice(candidates)
    try:
        await _finish_with_record(random_image, str(event.group_id), record, "随手翻图")
    except ImageLibraryError as exc:
        logger.exception("随机图片读取失败 group_id=%s image_id=%s error=%s", event.group_id, record.get("id"), exc)
        await random_image.finish("（翻到一页残卷）原图已经不在匣中，请掌柜清理记录。")


async def _handle_tag_edit(
    matcher,
    event: MessageEvent,
    args: Message,
    *,
    action: str,
) -> None:
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("（合上画匣）整理标签须回到原群落笔。")
    wait_seconds = _consume_image_rate(
        str(event.group_id),
        event.get_user_id(),
        "tag",
        IMAGE_TAG_RATE_LIMIT,
    )
    if wait_seconds:
        await matcher.finish(f"（按住墨签）改标签太密了，且等 {wait_seconds} 秒再落笔。")

    try:
        image_id, tags = _parse_tag_edit_args(args.extract_plain_text())
    except ValueError as exc:
        if str(exc) == "invalid_image_id":
            await matcher.finish(
                f"（递来墨签）用法：/{action} 图号 标签，例如 /{action} 12 猫猫 开心。"
            )
        if str(exc) == "too_many_image_tags":
            await matcher.finish("（墨签散了一桌）一次最多写八个标签。")
        await matcher.finish("（拈起标签）请写上短些的标签，莫留空白或怪字。")

    try:
        if action == "加标签":
            record = add_image_tags(str(event.group_id), image_id, tags)
            narration = "（替旧画添好墨签）"
        else:
            record = remove_image_tags(str(event.group_id), image_id, tags)
            narration = "（从旧画揭下墨签）"
    except ImageNotFoundError:
        await matcher.finish("（翻到空页）本群没有这个图号。")
    except ValueError as exc:
        if str(exc) == "too_many_image_tags":
            await matcher.finish("（画角贴得太满）一幅图最多留八个标签。")
        await matcher.finish("（拈起标签）这些墨签暂时写不上，请换个短些的名字。")
    except ImageLibraryError as exc:
        logger.exception(
            "图片标签修改失败 action=%s group_id=%s image_id=%s error=%s",
            action,
            event.group_id,
            image_id,
            exc,
        )
        await matcher.finish("（墨签忽被风吹散）这幅画的标签暂时改不了，请稍后再试。")

    await matcher.finish(
        f"{narration}图号 #{record.get('id')} 的标签已更新。\n"
        f"现有标签：{_format_record_tags(record)}\n"
        "『旧卷添删凭一字，他时寻影路分明。』"
    )


@add_tags.handle()
async def handle_add_tags(event: MessageEvent, args: Message = CommandArg()):
    await _handle_tag_edit(add_tags, event, args, action="加标签")


@remove_tags.handle()
async def handle_remove_tags(event: MessageEvent, args: Message = CommandArg()):
    await _handle_tag_edit(remove_tags, event, args, action="删标签")


@remove_image.handle()
async def handle_remove_image(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await remove_image.finish("（合上画匣）删图须回到原群落笔。")
    identifier = args.extract_plain_text().strip().lstrip("#")
    if not identifier.isdigit() or int(identifier) <= 0:
        await remove_image.finish("（递来朱笔）用法：/删图 图号，例如 /删图 12。")
    try:
        record = delete_image(
            str(event.group_id),
            int(identifier),
            actor_id=event.get_user_id(),
            allow_any=get_event_permission_level(event) >= 5,
        )
    except ImageNotFoundError:
        await remove_image.finish("（翻到空页）本群没有这个图号。")
    except ImagePermissionError:
        await remove_image.finish("（按住朱笔）只有原图发送者、收录者或首席掌柜能删这幅画。")
    except ImageLibraryError as exc:
        logger.exception("图片删除失败 group_id=%s image_id=%s error=%s", event.group_id, identifier, exc)
        await remove_image.finish("（朱笔忽然断锋）这幅画暂时删不干净，请稍后再试。")
    await remove_image.finish(
        f"（朱笔一点）图号 #{record.get('id')} 已从本群画匣移除。\n"
        "『旧影从今归夜色，空留一页待新图。』"
    )
