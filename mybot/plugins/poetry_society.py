from __future__ import annotations

from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="poetry_society",
    name="群诗社",
    default_enabled=True,
    scope="group",
    permission_level=2,
    data_files=("data/poetry_society.json",),
    privacy_level="sensitive",
    backup_policy="standard",
)

from datetime import datetime

from nonebot import get_bot, get_driver, on_command, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.admin import is_group_admin
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.json_store import JsonStoreReadError
from mybot.common.logger import get_plugin_logger
from mybot.common.poetry_society import (
    PoetrySocietyError,
    cast_vote,
    claim_notification,
    finish_notification,
    format_submission_id,
    get_history,
    get_overview,
    list_pending_notifications,
    list_works,
    recover_all_due,
    remove_work,
    submit_work,
    withdraw_work,
)


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("诗词文艺", "/诗社 - 每周主题投稿与投票", 55),
)
COMMAND_ALIASES = ("诗社", "群诗社")

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


poetry_society = on_command(
    "诗社",
    aliases={"群诗社"},
    priority=5,
    block=True,
)


def _format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _format_week(value: dict) -> str:
    return f"{value.get('year')}年第{int(value.get('week', 0))}周"


def _sender_name(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    return str(
        getattr(sender, "card", "")
        or getattr(sender, "nickname", "")
        or event.get_user_id()
    )


def _render_overview(week: dict) -> str:
    if week["phase"] == "open":
        phase = "开卷中，可投稿与投票"
        deadline = f"截卷：{_format_time(week['cutoff_at'])}"
    else:
        phase = "本周已结卷"
        deadline = f"再开：{_format_time(week['next_start_at'])}"
    return "\n".join(
        [
            "📜 李太白给·群诗社 📜",
            "（铺开长卷）本诗社每周悬一题，群友可落墨投稿、互投一票，待周末同看结卷。",
            "━━━━━━━━━━━━━━━━━━",
            f"周次：{_format_week(week)}",
            f"题目：{week['theme']}",
            f"阶段：{phase}",
            deadline,
            f"在卷作品：{week['active_submissions']} 篇",
            "━━━━━━━━━━━━━━━━━━",
            "每人每周一稿、一票，可在截卷前改投；不可自投。",
            "/诗社 投稿 <内容>",
            "/诗社 作品",
            "/诗社 投票 <编号>",
            "/诗社 撤稿",
            "/诗社 往卷",
            "/诗社 移除 <编号>（群管理）",
            "『一题邀来千家句，周末同看月下章。』",
        ]
    )


def _render_works(result: dict) -> str:
    week = result["week"]
    works = result["works"]
    lines = [
        "📖 李太白给·本周诗卷 📖",
        "━━━━━━━━━━━━━━━━━━",
        f"{_format_week(week)}｜题目：{week['theme']}",
    ]
    if not works:
        lines.extend(
            [
                "卷上尚无落墨，第一笔正候有缘人。",
                "『空卷不愁春色晚，一枝新句便成林。』",
            ]
        )
        return "\n".join(lines)

    settled = week["phase"] == "settled"
    for work in works:
        label = format_submission_id(work["id"])
        author = work.get("author_name") or work.get("author_id")
        if settled:
            lines.append(
                f"\n第{work.get('rank')}名｜{label}｜{work.get('votes', 0)}票｜{author}"
            )
        else:
            lines.append(f"\n{label}｜{author}")
        lines.append(str(work.get("content") or ""))
    lines.extend(
        [
            "\n━━━━━━━━━━━━━━━━━━",
            "票数在结卷前封存，免得一时风向扰了诗心。"
            if not settled
            else "本周票数与座次已定，长卷不再改笔。",
        ]
    )
    return "\n".join(lines)


def _render_history(result: dict) -> str:
    rows = result["history"]
    lines = ["🗞 李太白给·诗社往卷 🗞", "━━━━━━━━━━━━━━━━━━"]
    if not rows:
        lines.extend(["旧卷尚空，待本周结成第一章。", "『今日新题初落墨，他年回首便成篇。』"])
        return "\n".join(lines)
    for settlement in rows:
        label = f"{settlement.get('year')}年第{int(settlement.get('week', 0))}周"
        rankings = settlement.get("rankings", [])
        lines.append(f"\n【{label}｜{settlement.get('theme', '')}】")
        if not rankings:
            lines.append("本卷无人落稿，仍已照时封存。")
            continue
        top = rankings[0]
        author = top.get("author_name") or top.get("author_id")
        lines.append(
            f"榜首 {format_submission_id(top['id'])}｜{top.get('votes', 0)}票｜{author}"
        )
        lines.append(str(top.get("content") or ""))
    lines.extend(["\n━━━━━━━━━━━━━━━━━━", "『旧墨留香藏岁月，新题待客写风云。』"])
    return "\n".join(lines)


def _render_settlement(settlement: dict) -> str:
    lines = [
        "🏮 李太白给·群诗社结卷 🏮",
        "━━━━━━━━━━━━━━━━━━",
        f"{settlement.get('year')}年第{int(settlement.get('week', 0))}周",
        f"题目：{settlement.get('theme', '')}",
    ]
    rankings = settlement.get("rankings", [])
    if not rankings:
        lines.extend(
            [
                "本周长卷无人落墨，本猫仍照时封卷，静候下周新题。",
                "『空卷也曾承月色，来周再候一枝春。』",
            ]
        )
        return "\n".join(lines)

    if settlement.get("outcome") == "no_votes":
        lines.append("本周有诗无票，便依落墨先后排定卷次。")
    else:
        lines.append(
            f"共收 {settlement.get('total_submissions', 0)} 篇、"
            f"{settlement.get('total_votes', 0)} 票，座次如下："
        )
    for work in rankings[:3]:
        author = work.get("author_name") or work.get("author_id")
        lines.append(
            f"第{work.get('rank')}名 {format_submission_id(work['id'])}｜"
            f"{work.get('votes', 0)}票｜{author}"
        )
        lines.append(str(work.get("content") or ""))
    lines.extend(["━━━━━━━━━━━━━━━━━━", "『众笔同题分月色，一卷高悬待新章。』"])
    return "\n".join(lines)


async def _publish_pending_notifications(bot: Bot, group_id: str | None = None) -> None:
    try:
        pending = list_pending_notifications(group_id)
    except Exception as exc:
        logger.exception("读取诗社待发布结卷失败 group_id=%s: %s", group_id, exc)
        return
    for item in pending:
        target_group = item["group_id"]
        target_week = item["week_key"]
        try:
            settlement = claim_notification(target_group, target_week)
            if settlement is None:
                continue
            try:
                await bot.send_group_msg(
                    group_id=int(target_group),
                    message=_render_settlement(settlement),
                )
            except Exception as exc:
                finish_notification(target_group, target_week, success=False)
                logger.exception(
                    "诗社结卷通知发送失败 group_id=%s week=%s: %s",
                    target_group,
                    target_week,
                    exc,
                )
                continue
            finish_notification(target_group, target_week, success=True)
        except Exception as exc:
            logger.exception(
                "诗社结卷通知状态更新失败 group_id=%s week=%s: %s",
                target_group,
                target_week,
                exc,
            )


def _error_message(exc: PoetrySocietyError) -> str:
    messages = {
        "closed": "（合上诗卷）本周已截稿结卷，下周一零点再来落墨。",
        "duplicate_submission": "（按住墨纸）本周每人只留一稿；若想换篇，请先用 /诗社 撤稿。",
        "no_submission": "（翻了翻名页）本周没找到阁下仍在卷上的作品。",
        "text_only": "（收起画轴）诗社只收纯文字，请去掉图片、表情段或其他附件再投。",
        "empty_content": "（蘸了蘸空笔）稿子还没有可见文字，请添句诗再来。",
        "content_too_long": "（量过纸幅）作品最多 200 个可见字符，请略作删裁。",
        "invalid_submission_id": "（眯眼辨号）作品编号要写成正整数，例如 /诗社 投票 1。",
        "missing_submission": "（翻遍本卷）没找到这个作品编号，请先用 /诗社 作品 核对。",
        "old_submission": "（指向旧卷）这个编号不属本周，旧稿不能再收票或移除。",
        "inactive_submission": "（合上残页）这篇作品已撤下或移除，不能再操作。",
        "self_vote": "（压住酒盏）自己的诗留给旁人评，本猫不许自投。",
    }
    return messages.get(exc.code, "（护住诗卷）这一笔未能落下，请核对指令后再试。")


def _split_action(args: Message) -> tuple[str, str]:
    text = args.extract_plain_text().strip()
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def _is_text_only(args: Message) -> bool:
    return all(segment.type == "text" for segment in args)


async def _finish_store_error(exc: Exception) -> None:
    logger.exception("诗社运行数据读取或写入失败: %s", exc)
    await poetry_society.finish(
        "（护住卷匣）诗社旧卷眼下未能安全展开，本猫先不乱动；请稍后再试。"
    )


@poetry_society.handle()
async def handle_poetry_society(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
):
    if not isinstance(event, GroupMessageEvent):
        await poetry_society.finish("（抱住长卷）群诗社只在群中开席，请回群里唤本猫。")
    group_id = str(event.group_id)
    if not is_feature_enabled("poetry_society", group_id):
        await poetry_society.finish("（系起卷帘）本群诗社暂歇，待掌柜重新开卷。")

    try:
        overview = get_overview(group_id)
    except (JsonStoreReadError, PoetrySocietyError) as exc:
        await _finish_store_error(exc)
        return
    await _publish_pending_notifications(bot, group_id)

    action, payload = _split_action(args)
    if not action:
        await poetry_society.finish(_render_overview(overview["week"]))

    try:
        if action == "投稿":
            if not _is_text_only(args):
                raise PoetrySocietyError("text_only")
            if not payload:
                raise PoetrySocietyError("empty_content")
            result = submit_work(
                group_id,
                event.get_user_id(),
                payload,
                author_name=_sender_name(event),
            )
            await poetry_society.finish(
                f"（展平新笺）已收入本周诗卷，编号 "
                f"{format_submission_id(result['submission']['id'])}。\n"
                "若要换稿，请先用 /诗社 撤稿。"
            )

        if action == "作品":
            await poetry_society.finish(_render_works(list_works(group_id)))

        if action == "投票":
            result = cast_vote(group_id, event.get_user_id(), payload)
            label = format_submission_id(result["submission"]["id"])
            if result["changed"]:
                await poetry_society.finish(f"（挪动朱签）已改投 {label}，本周仍只记这一票。")
            await poetry_society.finish(f"（落下一枚朱签）已投给 {label}，截卷前仍可改投。")

        if action == "撤稿":
            result = withdraw_work(group_id, event.get_user_id())
            await poetry_society.finish(
                f"（抽回诗笺）{format_submission_id(result['submission']['id'])} 已撤下；"
                "旧票一并作废，可重新投稿。"
            )

        if action == "往卷":
            await poetry_society.finish(_render_history(get_history(group_id)))

        if action == "移除":
            if not is_group_admin(event):
                await poetry_society.finish("（按住卷册）移除他人作品须有本群现有管理权限。")
            result = remove_work(group_id, payload, event.get_user_id())
            await poetry_society.finish(
                f"（收起不合宜的一页）{format_submission_id(result['submission']['id'])} "
                "已移出本周诗卷，关联选票一并作废。"
            )

        await poetry_society.finish(
            "（敲敲卷轴）可用：投稿、作品、投票、撤稿、往卷、移除。\n"
            "输入 /诗社 可查看本周题目与完整用法。"
        )
    except PoetrySocietyError as exc:
        await poetry_society.finish(_error_message(exc))
    except JsonStoreReadError as exc:
        await _finish_store_error(exc)


async def _startup_recovery() -> None:
    try:
        recovered = recover_all_due()
        if recovered:
            logger.info("诗社启动补结卷完成 count=%s", len(recovered))
    except Exception as exc:
        logger.exception("诗社启动补结卷失败: %s", exc)


get_driver().on_startup(_startup_recovery)


@scheduler.scheduled_job(
    "cron",
    day_of_week="sun",
    hour=21,
    minute=0,
    timezone="Asia/Shanghai",
    id="poetry_society_weekly_settlement",
)
async def weekly_poetry_society_settlement() -> None:
    try:
        recover_all_due()
    except Exception as exc:
        logger.exception("诗社周结卷失败: %s", exc)
        return
    try:
        bot: Bot = get_bot()
    except Exception as exc:
        logger.warning("诗社周结卷暂未取得 bot，通知留待下次交互: %s", exc)
        return
    await _publish_pending_notifications(bot)
