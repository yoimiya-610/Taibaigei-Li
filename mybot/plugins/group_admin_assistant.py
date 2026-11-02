from __future__ import annotations

from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="group_admin_assistant",
    name="群管理助手",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=(
        "data/group_activities.json",
        "data/group_activity_archive.json",
        "data/group_card_queue.json",
        "data/group_card_sync.json",
        "data/group_essence.json",
        "data/group_message_index.json",
    ),
    privacy_level="sensitive",
    backup_policy="standard",
)

import re
from datetime import datetime

from nonebot import get_bot, on_command, on_message, on_notice, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, NoticeEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.admin import get_event_permission_level
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.group_management import (
    allow_poke,
    append_chain,
    archive_activity,
    authorize_card,
    build_candidates,
    clear_essence_pending,
    clear_activity_archives,
    create_activity,
    disable_card,
    due_card_jobs,
    expire_due_activities,
    finish_activity,
    get_activity,
    get_card_record,
    group_activity,
    index_message,
    join_activity,
    leave_activity,
    list_activity_archives,
    mark_essence_pending,
    normalize_card_format,
    queue_card_sync,
    record_emoji_likes,
    remove_card_job,
    render_card,
    retry_card_job,
    set_activity_deadline,
    sync_essence_event,
    weekly_digest,
)
from mybot.common.group_platform import (
    PlatformOperationError,
    delete_essence,
    get_member,
    group_poke,
    require_bot_manager,
    require_platform_managers,
    set_essence,
    set_group_card,
)
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.message_utils import get_first_at_user_id, get_reply_message_id
from mybot.common.titles import get_display_title


HELP_ITEMS = (
    HelpItem("系统说明", "/群管理介绍 - 翻看群中掌事、名帖与活动的规矩", 30),
    HelpItem("系统说明", "/唤醒 @某人 - 请本猫戳醒群友", 31),
)
COMMAND_ALIASES = (
    "加精", "取消加精", "精华候选", "精华确认", "本周精华",
    "同步名片", "名片格式", "恢复名片", "唤醒", "活动", "群管理介绍",
)
PUBLIC_COMMANDS = (
    "本周精华", "同步名片", "名片格式", "恢复名片", "唤醒", "活动", "群管理介绍",
)
logger = get_plugin_logger(__name__)


def _group_admin_enabled(group_id: str | int) -> bool:
    return is_feature_enabled("group_admin_assistant", group_id)


def _group(event: MessageEvent) -> tuple[str, str]:
    if not isinstance(event, GroupMessageEvent):
        raise ValueError("group_only")
    return str(event.group_id), event.get_user_id()


def _name(event: GroupMessageEvent) -> str:
    sender = event.sender
    return str(getattr(sender, "card", "") or getattr(sender, "nickname", "") or event.user_id)


def _platform_message(category: str) -> str:
    messages = {
        "operator_not_manager": "（压住酒壶）此事还须群主或群管理员亲自落笔。",
        "bot_not_manager": "（摸摸空袖）本猫在此群尚无掌事腰牌，这一笔暂落不下。",
        "unavailable": "（墨锋一顿）群中这道手续暂未办成，稍后再试。",
        "invalid_response": "（翻过空页）群中回音不全，这次先不贸然动笔。",
    }
    return messages.get(category, messages["unavailable"])


async def _require_level(matcher, event: MessageEvent, level: int) -> None:
    if get_event_permission_level(event) < level:
        await matcher.finish("（合上掌事簿）这道群务需掌柜权限方可落笔。")


async def _essence_action(matcher, bot: Bot, event: MessageEvent, operation: str) -> None:
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await matcher.finish("（收起朱笔）群精华只在群中办理。")
    await _require_level(matcher, event, 3)
    message_id = get_reply_message_id(event)
    if not message_id:
        await matcher.finish("（点点案头）请回复目标消息，再让本猫落这枚朱印。")
    try:
        await require_platform_managers(bot, group_id, user_id)
        mark_essence_pending(group_id, message_id, operation)
        if operation == "add":
            await set_essence(bot, message_id)
        else:
            await delete_essence(bot, message_id)
        sync_essence_event(group_id, message_id, operation)
    except PlatformOperationError as exc:
        clear_essence_pending(group_id, message_id)
        logger.exception("群精华操作失败 group_id=%s message_id=%s operation=%s", group_id, message_id, operation)
        await matcher.finish(_platform_message(exc.category))
    verb = "收入群精华" if operation == "add" else "移出群精华"
    await matcher.finish(f"（朱笔落印）此句已{verb}。\n『群言有光，宜留一页。』")


add_essence = on_command("加精", priority=4, block=True)
delete_essence_cmd = on_command("取消加精", priority=4, block=True)
essence_candidates = on_command("精华候选", priority=4, block=True)
confirm_essence = on_command("精华确认", priority=4, block=True)
weekly_essence = on_command("本周精华", priority=5, block=True)


@add_essence.handle()
async def handle_add_essence(bot: Bot, event: MessageEvent):
    await _essence_action(add_essence, bot, event, "add")


@delete_essence_cmd.handle()
async def handle_delete_essence(bot: Bot, event: MessageEvent):
    await _essence_action(delete_essence_cmd, bot, event, "delete")


def _render_candidate(item: dict, index: int) -> str:
    likes = "未取得" if item.get("likes") is None else str(item["likes"])
    mode = "达观察阈值" if item.get("candidate_mode") == "threshold" else "近期降级候选"
    return (
        f"{index}. {item.get('nickname') or item.get('user_id')}：{item.get('text')}\n"
        f"   回应 {likes}｜已观察回复 {item.get('replies', 0)}｜{mode}"
    )


@essence_candidates.handle()
async def handle_candidates(event: MessageEvent):
    try:
        group_id, _ = _group(event)
    except ValueError:
        await essence_candidates.finish("（收起册页）候选只在群中查看。")
    await _require_level(essence_candidates, event, 3)
    items = build_candidates(group_id)
    if not items:
        await essence_candidates.finish("（翻过新页）眼下尚无可核验的精华候选。")
    await essence_candidates.finish(
        "📜 群精华候选\n"
        "互动数字只统计本猫实际收到的消息与回应，缺项不作猜测。\n"
        + "\n".join(_render_candidate(item, index) for index, item in enumerate(items, 1))
        + "\n用 /精华确认 编号 落印。"
    )


@confirm_essence.handle()
async def handle_confirm_essence(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await confirm_essence.finish("（收起朱笔）群精华只在群中办理。")
    await _require_level(confirm_essence, event, 3)
    raw = args.extract_plain_text().strip()
    if not raw.isdigit():
        await confirm_essence.finish("（指向候选簿）用法：/精华确认 编号")
    items = build_candidates(group_id)
    index = int(raw) - 1
    if not 0 <= index < len(items):
        await confirm_essence.finish("（翻遍候选簿）这个编号已经不在册中。")
    message_id = str(items[index]["message_id"])
    try:
        await require_platform_managers(bot, group_id, user_id)
        mark_essence_pending(group_id, message_id, "add")
        await set_essence(bot, message_id)
        sync_essence_event(group_id, message_id, "add")
    except PlatformOperationError as exc:
        clear_essence_pending(group_id, message_id)
        logger.exception("确认群精华失败 group_id=%s message_id=%s", group_id, message_id)
        await confirm_essence.finish(_platform_message(exc.category))
    await confirm_essence.finish("（朱笔落印）候选已收入群精华。\n『众声淘尽，留此清光。』")


@weekly_essence.handle()
async def handle_weekly_essence(event: MessageEvent):
    try:
        group_id, _ = _group(event)
    except ValueError:
        await weekly_essence.finish("（合上周册）群中旧话，要回群里翻。")
    items = weekly_digest(group_id)
    if not items:
        await weekly_essence.finish("（翻过七日薄册）本周尚无足够记录可供回看。")
    await weekly_essence.finish(
        "📖 本周群聊回光（只读摘要）\n"
        + "\n".join(f"{index}. {item.get('nickname')}：{item.get('text')}" for index, item in enumerate(items, 1))
        + "\n『只翻旧页，不动朱印。』"
    )


sync_card = on_command("同步名片", priority=5, block=True)
card_format = on_command("名片格式", priority=5, block=True)
restore_card = on_command("恢复名片", priority=5, block=True)
group_management_intro = on_command("群管理介绍", priority=5, block=True)


@group_management_intro.handle()
async def handle_group_management_intro():
    await group_management_intro.finish(
        "🪶 李太白给·群管理介绍\n"
        "（展平群中旧卷）掌事有掌事的朱笔，群友也有自己的名帖与活动簿。\n"
        "/精华候选 - 查看群精华候选（需群务掌柜权限）\n"
        "/本周精华 - 回看一周群聊亮点\n"
        "/同步名片 - 自愿同步称号与群名片\n"
        "/唤醒 @某人 - 请本猫戳醒群友\n"
        "/活动 - 创建、参与和主持群活动\n"
        "『各守一方笔，共成满卷春。』"
    )


async def _authorize_and_apply(matcher, bot: Bot, event: MessageEvent, format_text: str) -> None:
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await matcher.finish("（收起名帖）群名片须在群中整理。")
    try:
        member = await get_member(bot, group_id, user_id)
        nickname = str(member.get("nickname") or _name(event))
        original = str(member.get("card") or "")
        normalized_format = normalize_card_format(format_text)
        title = get_display_title(user_id, group_id)["title"]
        card = render_card(normalized_format, title, nickname)
        await require_bot_manager(bot, group_id)
        await set_group_card(bot, group_id, user_id, card)
        authorize_card(group_id, user_id, original, nickname, normalized_format)
        remove_card_job(group_id, user_id)
    except ValueError:
        await matcher.finish("（裁去乱纹）名片格式只可使用“【称号】”与“昵称”，且须保留昵称。")
    except PlatformOperationError as exc:
        logger.exception("同步群名片失败 group_id=%s user_id=%s", group_id, user_id)
        await matcher.finish(_platform_message(exc.category))
    await matcher.finish(f"（抚平名帖）已按阁下心意写作：{card}")


@sync_card.handle()
async def handle_sync_card(bot: Bot, event: MessageEvent):
    record = None
    if isinstance(event, GroupMessageEvent):
        record = get_card_record(str(event.group_id), event.get_user_id())
    await _authorize_and_apply(sync_card, bot, event, str(record.get("format")) if record else "【称号】昵称")


@card_format.handle()
async def handle_card_format(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    if not raw:
        await card_format.finish("（铺开名帖）用法：/名片格式 【称号】昵称")
    try:
        normalize_card_format(raw)
    except ValueError:
        await card_format.finish("（裁去乱纹）只可使用“【称号】”与“昵称”，且须保留昵称。")
    await _authorize_and_apply(card_format, bot, event, raw)


@restore_card.handle()
async def handle_restore_card(bot: Bot, event: MessageEvent):
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await restore_card.finish("（收起名帖）群名片须在群中整理。")
    record = get_card_record(group_id, user_id)
    if not record or not record.get("enabled"):
        await restore_card.finish("（翻过名帖）阁下尚未托本猫同步名片，无须恢复。")
    try:
        await set_group_card(bot, group_id, user_id, str(record.get("original_card", "")))
    except PlatformOperationError as exc:
        logger.exception("恢复群名片失败 group_id=%s user_id=%s", group_id, user_id)
        await restore_card.finish(_platform_message(exc.category))
    disable_card(group_id, user_id)
    await restore_card.finish("（拂去新墨）旧名片已还原，此后也不再随称号改动。")


wake = on_command("唤醒", priority=4, block=True)


@wake.handle()
async def handle_wake(bot: Bot, event: MessageEvent):
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await wake.finish("（收回猫爪）唤醒只在群里施展。")
    target_id = get_first_at_user_id(event)
    if not target_id:
        await wake.finish("（抬起猫爪）请用 /唤醒 @某人 指明对象。")
    if target_id == str(bot.self_id):
        await wake.finish("（扶正墨镜）本猫醒着呢，不劳自己戳自己。")
    if not allow_poke(group_id, user_id):
        await wake.finish("（按住猫爪）刚唤过一回，且让群中清静片刻。")
    try:
        await require_bot_manager(bot, group_id)
        await get_member(bot, group_id, target_id)
        await group_poke(bot, group_id, target_id)
    except PlatformOperationError as exc:
        logger.exception("群内唤醒失败 group_id=%s target_id=%s", group_id, target_id)
        await wake.finish(_platform_message(exc.category))
    await wake.finish("（伸爪轻点）醒醒，诗会尚未散席。")


activity = on_command("活动", priority=5, block=True)


def _can_manage_activity(event: MessageEvent, current: dict) -> bool:
    return event.get_user_id() == str(current.get("creator_id")) or get_event_permission_level(event) >= 3


def _parse_duration(value: str) -> int:
    match = re.fullmatch(r"(\d+)(秒|分钟|分|小时|时)?", value.strip())
    if not match:
        raise ValueError("invalid_duration")
    amount = int(match.group(1))
    unit = match.group(2) or "秒"
    return amount * (3600 if unit in {"小时", "时"} else 60 if unit in {"分钟", "分"} else 1)


def _activity_status_text(status: str) -> str:
    return {
        "active": "进行中",
        "finished": "已截止",
        "cancelled": "已取消",
    }.get(str(status), "状态待核")


@activity.handle()
async def handle_activity(event: MessageEvent, args: Message = CommandArg()):
    try:
        group_id, user_id = _group(event)
    except ValueError:
        await activity.finish("（收起活动簿）群中活动须在群里主持。")
    raw = args.extract_plain_text().strip()
    if not raw:
        current = get_activity(group_id)
        if not current:
            await activity.finish("（摊开空册）用法：/活动 创建 名称")
        await activity.finish(
            f"🎐 {current['name']}｜{_activity_status_text(current['status'])}\n"
            f"报名 {len(current.get('participants', {}))} 人｜接龙 {len(current.get('chain', []))} 条"
        )
    action, _, value = raw.partition(" ")
    try:
        if action == "创建":
            current = create_activity(group_id, user_id, value)
            await activity.finish(f"（挂起新牌）活动“{current['name']}”已开场，可用 /活动 报名。")
        if action == "报名":
            count = join_activity(group_id, user_id, _name(event))
            await activity.finish(f"（添上一笔）已报名，当前共 {count} 人。")
        if action == "退出":
            count = leave_activity(group_id, user_id)
            await activity.finish(f"（划去一笔）已退出，当前还余 {count} 人。")
        if action == "接龙":
            number = append_chain(group_id, user_id, _name(event), value)
            await activity.finish(f"（续上一句）接龙第 {number} 笔已记下。")
        if action == "历史":
            items = list_activity_archives(group_id)
            if not items:
                await activity.finish("（翻过旧匣）本群尚无活动归档。")
            await activity.finish(
                "📚 活动归档\n"
                + "\n".join(
                    f"{index}. {item['name']}｜{_activity_status_text(item['status'])}"
                    for index, item in enumerate(items, 1)
                )
            )
        if action == "清理":
            if get_event_permission_level(event) < 3:
                await activity.finish("（扣住旧匣）清理归档需群务掌柜权限。")
            count = clear_activity_archives(group_id)
            await activity.finish(f"（拂去旧页）已清理 {count} 份活动归档。")

        current = get_activity(group_id)
        if not current:
            raise ValueError("no_activity")
        if not _can_manage_activity(event, current):
            await activity.finish("（按住主持簿）此项由创建者或群务掌柜办理。")
        if action == "分组":
            groups = group_activity(group_id, int(value))
            lines = [
                f"第 {index} 组：" + "、".join(name for _, name in members)
                for index, members in enumerate(groups, 1)
            ]
            await activity.finish("（竹签落案，种子已存档）\n" + "\n".join(lines))
        if action == "点名":
            names = list(current.get("participants", {}).values())
            if not names:
                raise ValueError("no_participants")
            seed = f"{current['id']}:{len(current.get('chain', []))}:{datetime.now().date()}"
            index = int.from_bytes(seed.encode(), "little") % len(names)
            await activity.finish(f"（竹签一转）这一回点到：{names[index]}")
        if action == "计时":
            deadline = set_activity_deadline(group_id, _parse_duration(value))
            await activity.finish(f"（翻转沙漏）计时已起，截止于 {deadline}。")
        if action in {"截止", "取消"}:
            result = finish_activity(group_id, "finished" if action == "截止" else "cancelled")
            await activity.finish(f"（合上活动簿）“{result['name']}”已{action}。")
        if action == "结果":
            groups = current.get("groups", [])
            await activity.finish(
                f"📜 {current['name']} 结果\n报名 {len(current.get('participants', {}))} 人"
                + (f"\n分组 {len(groups)} 组｜审计种子 {current.get('seed')}" if groups else "")
            )
        if action == "归档":
            result = archive_activity(group_id)
            await activity.finish(f"（收入旧匣）“{result['name']}”结果已归档。")
        await activity.finish("（指向活动簿）可用：创建、报名、退出、接龙、分组、点名、计时、截止、取消、结果、归档、历史、清理。")
    except (TypeError, ValueError) as exc:
        messages = {
            "activity_exists": "本群已有活动在场，先截止或取消旧场。",
            "no_activity": "本群眼下没有进行中的活动。",
            "no_participants": "活动簿上尚无人报名。",
            "invalid_group_count": "分组数量须为正整数。",
            "invalid_duration": "计时示例：/活动 计时 10分钟。",
            "missing_content": "接龙内容不可为空。",
            "activity_not_finished": "活动尚未截止或取消，暂不能归档。",
        }
        await activity.finish(f"（翻过空页）{messages.get(str(exc), '这道活动指令未写明白。')}")


def _all_group_messages(event) -> bool:
    return isinstance(event, GroupMessageEvent)


message_indexer = on_message(rule=Rule(_all_group_messages), priority=98, block=False)


@message_indexer.handle()
async def handle_message_index(event: GroupMessageEvent):
    if not _group_admin_enabled(event.group_id):
        return
    try:
        index_message(
            str(event.group_id), str(event.message_id), event.get_user_id(), _name(event),
            event.get_plaintext(), get_reply_message_id(event), getattr(event, "time", None),
        )
    except Exception as exc:
        logger.exception("群消息索引失败 group_id=%s message_id=%s: %s", event.group_id, event.message_id, exc)


notice_collector = on_notice(priority=20, block=False)


@notice_collector.handle()
async def handle_group_notice(event: NoticeEvent):
    data = event.model_dump() if hasattr(event, "model_dump") else event.dict()
    group_id = str(data.get("group_id", ""))
    if not group_id or not _group_admin_enabled(group_id):
        return
    try:
        notice_type = str(data.get("notice_type", ""))
        message_id = str(data.get("message_id", ""))
        if notice_type == "essence" and group_id and message_id:
            sync_essence_event(
                group_id, message_id, str(data.get("sub_type", "")),
                str(data.get("sender_id", "")), str(data.get("operator_id", "")),
            )
        elif notice_type == "group_msg_emoji_like" and group_id and message_id:
            record_emoji_likes(group_id, message_id, data.get("likes", []))
    except Exception as exc:
        logger.exception("群管理通知同步失败 notice_type=%s: %s", data.get("notice_type"), exc)


require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


@scheduler.scheduled_job("interval", seconds=30, id="group_card_sync_queue")
async def process_card_queue():
    for job in due_card_jobs():
        group_id, user_id = str(job["group_id"]), str(job["user_id"])
        if not _group_admin_enabled(group_id):
            continue
        record = get_card_record(group_id, user_id)
        if not record or not record.get("enabled"):
            remove_card_job(group_id, user_id)
            continue
        try:
            bot = get_bot()
            title = get_display_title(user_id, group_id)["title"]
            card = render_card(record["format"], title, record.get("nickname", user_id))
            await set_group_card(bot, group_id, user_id, card)
            remove_card_job(group_id, user_id)
        except Exception as exc:
            retry_card_job(group_id, user_id)
            logger.exception("群名片队列执行失败 group_id=%s user_id=%s: %s", group_id, user_id, exc)


@scheduler.scheduled_job("interval", seconds=15, id="group_activity_deadlines")
async def process_activity_deadlines():
    for group_id, current in expire_due_activities(group_filter=_group_admin_enabled):
        try:
            bot = get_bot()
            await bot.send_group_msg(
                group_id=group_id,
                message=f"（沙漏见底）活动“{current['name']}”计时已到，结果已封存待归档。",
            )
        except Exception as exc:
            logger.exception("活动到时通知失败 group_id=%s activity_id=%s: %s", group_id, current.get("id"), exc)
