from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="fortune",
    name="签到运势",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=("data/fortune_data.json", "data/points.json", "data/paid_rounds.json"),
    privacy_level="personal",
    backup_policy="standard",
)

import hashlib
import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.params import CommandArg
from nonebot.rule import Rule

# 导入积分系统
from mybot.common.accounting import add_points_once, get_points
from mybot.common.admin import is_admin_user, normalize_id
from mybot.common.admin_audit import record_admin_action
from mybot.common.help_registry import HelpItem
from mybot.common.message_utils import get_message_text
from mybot.common.json_store import mutate_json
from mybot.common.logger import get_plugin_logger
from mybot.common.streak import (
    DATA_FILE,
    DEFAULT_FORTUNE_DATA,
    calculate_current_streak,
    fortune_record_key as _fortune_record_key,
    get_current_streak,
    get_streak_evaluation,
    load_data,
    save_data,
    streak_key as _streak_key,
    sync_streak as _sync_streak,
)
from mybot.common.titles import get_display_title, grant_title, roll_title_fortune_bonus
from mybot.common.user_utils import get_nickname
from mybot.common.usage_policy import (
    OPERATION_AWAITING_CONFIRMATION,
    OPERATION_COMPLETED,
    PaidOperationExpired,
    PaidOperationInsufficientBalance,
    PaidOperationService,
    paid_operation_processing_message,
    paid_operation_refund_message,
    request_fingerprint,
)

from mybot.plugins._fortune.advice import JI_ITEMS, YI_ITEMS
from mybot.plugins._fortune import storage as _fortune_storage
from mybot.plugins._fortune.copy import (
    FORTUNE_LIST,
    FORTUNE_POINTS,
    FORTUNE_POEMS,
    FORTUNE_WEIGHTS,
    LUCKY_COLORS,
    MAKEUP_CONFIRM_TTL_SECONDS,
    POET_COMMENTS,
    PUBLIC_PLAY_GUIDES,
    SPECIAL_EVENTS,
    UNKNOWN_FORTUNE_DESCRIPTIONS,
    UNKNOWN_FORTUNE_DETAILS,
    UNKNOWN_FORTUNE_NAME,
    UNKNOWN_FORTUNE_TITLE_ID,
    _public_fortune_points_text,
)
from mybot.plugins._fortune.rules import (
    MIN_MAKEUP_COST,
    STREAK_MULTIPLIER_CAP_DAY,
    STREAK_MULTIPLIER_MAX_TENTHS,
    STREAK_MULTIPLIER_MIN_TENTHS,
    STREAK_MULTIPLIER_START_DAY,
    _award_tx_id,
    _special_event_label,
    apply_streak_multiplier,
    calculate_fortune_score,
    calculate_makeup_cost,
    check_streak,
    format_streak_multiplier,
    get_streak_bonus,
    get_streak_multiplier_tenths,
)

_find_makeup_target_date = _fortune_storage._find_makeup_target_date
_makeup_usage_key = _fortune_storage._makeup_usage_key


HELP_ITEMS = (
    HelpItem("签到积分", "/签到 - 每日运势签到", 10),
    HelpItem("签到积分", "/补签 - 整次补齐恢复历史连签，10积分起", 15),
)
COMMAND_ALIASES = (
    "运势", "今日运势", "求运势", "抽签", "求签", "签到", "今日签到", "每日签到", "打卡",
    "补签",
)

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
logger = get_plugin_logger(__name__)


def current_datetime() -> datetime:
    return datetime.now(APP_TIMEZONE)


def current_date() -> date:
    return current_datetime().date()


def _get_makeup_plan(data: dict, user_id: str, group_id: str) -> dict:
    now = current_datetime()
    today_date = now.date()
    today_text = today_date.strftime("%Y-%m-%d")
    restoration = _fortune_storage.plan_makeup_dates(data, user_id, group_id, today_date)
    if restoration["status"] != "available":
        return {**restoration, "year": now.year, "today_date": today_text}

    usage_key = _makeup_usage_key(now.year, user_id, group_id)
    usage = data.get("makeup_usage", {}).get(usage_key, {})
    used_count = int(usage.get("count", 0))
    next_count = used_count + 1
    return {
        **restoration,
        "target_date": restoration["target_dates"][-1],
        "today_date": today_text,
        "year": now.year,
        "used_count": used_count,
        "next_count": next_count,
        "cost": calculate_makeup_cost(next_count),
    }


def get_makeup_plan(user_id: str, group_id: str) -> dict:
    return _get_makeup_plan(load_data(), user_id, group_id)


def _makeup_request_key(plan: dict) -> str:
    return request_fingerprint(
        plan["today_date"], plan["target_dates"], plan["historical_longest"],
        plan["restored_streak"], plan["next_count"], plan["cost"],
    )


def _refresh_today_fortune_streak_after_makeup(
    data: dict,
    user_id: str,
    group_id: str,
    today_text: str,
    streak_count: int,
) -> bool:
    record = data.setdefault("fortune_record", {}).get(_fortune_record_key(today_text, user_id, group_id))
    if not isinstance(record, dict):
        return False

    try:
        previous_count = int(record.get("streak_count", 0))
    except (TypeError, ValueError):
        previous_count = 0

    if previous_count >= streak_count:
        return False

    record["streak_count_before_makeup"] = previous_count
    record["streak_count"] = streak_count
    record["streak_repaired_by_makeup"] = True
    return True


def _apply_makeup(
    user_id: str, group_id: str, expected_cost: int, expected_request_key: str | None = None,
) -> dict:
    def mutator(data: dict) -> dict:
        plan = _get_makeup_plan(data, user_id, group_id)
        if plan["status"] != "available":
            return plan
        if plan["cost"] != expected_cost:
            return {**plan, "status": "cost_changed"}
        if expected_request_key is not None and _makeup_request_key(plan) != expected_request_key:
            return {**plan, "status": "plan_changed"}

        record_key = _streak_key(user_id, group_id)
        records = data.setdefault("makeup_records", {}).setdefault(record_key, {"dates": []})
        records.setdefault("dates", []).extend(plan["target_dates"])

        usage_key = _makeup_usage_key(plan["year"], user_id, group_id)
        data.setdefault("makeup_usage", {})[usage_key] = {"count": plan["next_count"]}
        today_date = datetime.strptime(plan["today_date"], "%Y-%m-%d").date()
        streak_count = _sync_streak(data, user_id, group_id, today_date)
        today_record_repaired = _refresh_today_fortune_streak_after_makeup(
            data,
            user_id,
            group_id,
            plan["today_date"],
            streak_count,
        )
        return {
            **plan,
            "status": "created",
            "streak_count": streak_count,
            "today_record_repaired": today_record_repaired,
        }

    return mutate_json(DATA_FILE, DEFAULT_FORTUNE_DATA, mutator)

# 运势列表
def get_daily_fortune(user_id: str, fortune_date: date | None = None):
    """根据用户ID和日期生成固定的每日运势（全局一致）"""
    fortune_date = fortune_date or current_date()
    today = fortune_date.strftime("%Y%m%d")
    seed_text = f"{user_id}_{today}_fortune"
    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    
    # 固定运势结果
    fortune_result = rng.choices(FORTUNE_LIST, weights=FORTUNE_WEIGHTS, k=1)[0]
    fortune_name, emoji, desc = fortune_result
    
    if fortune_name == UNKNOWN_FORTUNE_NAME:
        # 隐藏签固定数字、颜色与宜忌，其余文案仍从专属池中抽取。
        special_event = None
        desc = rng.choice(UNKNOWN_FORTUNE_DESCRIPTIONS)
        poet_comment = rng.choice(POET_COMMENTS[fortune_name])
        poem = rng.choice(FORTUNE_POEMS[fortune_name])
        lucky_number = UNKNOWN_FORTUNE_DETAILS["lucky_number"]
        lucky_color = UNKNOWN_FORTUNE_DETAILS["lucky_color"]
        yi_list = UNKNOWN_FORTUNE_DETAILS["yi"]
        ji_list = UNKNOWN_FORTUNE_DETAILS["ji"]
    else:
        # 固定特殊事件（20%概率）
        special_event = None
        if rng.random() < 0.20:
            special_event = rng.choice(SPECIAL_EVENTS)

        # 固定评语和诗句
        poet_comment = rng.choice(POET_COMMENTS[fortune_name])
        poem = rng.choice(FORTUNE_POEMS[fortune_name])

        # 固定幸运数字、颜色、宜忌
        lucky_number = rng.randint(0, 99)
        lucky_color = rng.choice(LUCKY_COLORS)
        yi_list = rng.sample(YI_ITEMS, 3)
        ji_list = rng.sample(JI_ITEMS, 2)
    
    return {
        "fortune_name": fortune_name,
        "emoji": emoji,
        "desc": desc,
        "special_event": special_event,
        "poet_comment": poet_comment,
        "poem": poem,
        "lucky_number": lucky_number,
        "lucky_color": lucky_color,
        "yi": yi_list,
        "ji": ji_list
    }

def _build_fortune_record(
    date_text: str,
    user_id: str,
    group_id: str,
    daily: dict,
    score: dict,
    streak_count: int,
    award_tx_id: str,
) -> dict:
    return {
        "date": date_text,
        "user_id": user_id,
        "group_id": group_id,
        "fortune": daily["fortune_name"],
        "emoji": daily["emoji"],
        "desc": daily["desc"],
        "special_event": _special_event_label(daily["special_event"]),
        "poet_comment": daily["poet_comment"],
        "poem": daily["poem"],
        "lucky_number": daily["lucky_number"],
        "lucky_color": daily["lucky_color"],
        "yi": list(daily["yi"]),
        "ji": list(daily["ji"]),
        "base_points": score["base_points"],
        "total_points": score["total_points"],
        "streak_count": streak_count,
        "streak_multiplier": score["streak_multiplier"],
        "title_bonus": dict(score.get("title_bonus", {})),
        "award_tx_id": award_tx_id,
        "points_awarded": False,
    }


def _mark_fortune_points_awarded(key: str, award_tx_id: str) -> None:
    _fortune_storage.mark_fortune_points_awarded(DATA_FILE, key, award_tx_id)


def _join_items(value) -> str:
    if isinstance(value, list):
        return " / ".join(str(item) for item in value)
    return str(value or "旧签册未留")


def _format_titled_nickname(user_id: str, group_id: str, nickname: str) -> str:
    title_info = get_display_title(user_id, group_id, get_points(user_id, group_id))
    if str(title_info.get("title_id", "")) == "default":
        return nickname
    title = str(title_info.get("title", "")).strip()
    if not title:
        return nickname
    return f"【{title}】{nickname}"


def _render_streak_status(record: dict) -> str:
    streak_count = record.get("streak_count", 0)
    if record.get("streak_repaired_by_makeup"):
        return f"🔥 连续签到 {streak_count} 天（补签已续上，今日积分按原签入账）"

    return f"🔥 连续签到 {streak_count} 天"


def _render_full_fortune(
    nickname: str,
    record: dict,
    hidden_title_text: str = "",
    prefix_text: str = "",
    point_label: str = "今日获得",
) -> str:
    special_text = f"\n✨ 特殊事件：{record['special_event']}" if record.get("special_event") else ""
    title_bonus = record.get("title_bonus", {}) if isinstance(record.get("title_bonus"), dict) else {}
    title_power_text = ""
    if title_bonus.get("activated"):
        title_power_text = (
            f"\n🎖 称号之力：使用了“{title_bonus.get('title', '旧名号')}”的力量，积分翻倍"
            f"（{title_bonus.get('rarity', 'R')}，触发率 {title_bonus.get('trigger_rate', 1)}%）"
        )
    streak_status = _render_streak_status(record)
    output = f"""🎋 李太白给·今日运势签 🎋
{'='*20}
✦ {nickname} の运势 ✦
{'='*20}{prefix_text}
【运势】{record['fortune']} {record['emoji']}{special_text}
【解读】{record['desc']}
{'='*20}
🔢 幸运数字：{record.get('lucky_number', '旧签册未留')}
🎨 幸运颜色：{record.get('lucky_color', '旧签册未留')}
✅ 宜：{_join_items(record.get('yi'))}
❌ 忌：{_join_items(record.get('ji'))}
{'='*20}
📜 诗人曰：
{record.get('poet_comment', '本猫翻着旧签册，只见墨痕尚温。')}

『{record.get('poem', '旧签已落青册里，今日重看仍有风。')}』
{'='*20}
{streak_status}
💰 {point_label} {record.get('total_points', 0)} 积分{title_power_text}{hidden_title_text}"""
    return output


def _render_compact_existing_fortune(nickname: str, record: dict) -> str:
    special_text = ""
    if record.get("special_event"):
        special_text = f"\n✨ 特殊事件：{record['special_event']}"
    return (
        f"『{nickname}』你今天在本群已经抽过签了！\n"
        f"（翻开旧册）这页是旧式简录，墨痕尚在。\n\n"
        f"【今日运势】{record.get('fortune', '未知')} {record.get('emoji', '')}{special_text}\n"
        f"【运势解读】{record.get('desc', '旧签册未留解读。')}\n"
        f"『一日一签天有定，重翻旧页也生香。』"
    )

FORTUNE_TRIGGERS = {"运势", "今日运势", "求运势", "抽签", "求签", "签到", "今日签到", "每日签到", "打卡"}


def is_plain_fortune(event: MessageEvent) -> bool:
    return get_message_text(event) in FORTUNE_TRIGGERS


fortune = on_command("运势", aliases={"今日运势", "求运势", "抽签", "求签", "签到", "今日签到", "每日签到", "打卡"}, priority=5, block=True)
fortune_plain = on_message(rule=Rule(is_plain_fortune), priority=5, block=True)


async def send_fortune(matcher, bot: Bot, event: MessageEvent):
    # 私聊不支持
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish(
            "（合上签筒）签到请在群里落笔。\n"
            "『独坐书房签不响，入群方有满堂风。』"
        )
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    today_date = current_date()
    today = today_date.strftime("%Y-%m-%d")
    key = f"{today}_{group_id}_{user_id}"
    award_tx_id = _award_tx_id(key)
    
    nickname = await get_nickname(bot, user_id, context="运势")
    display_name = _format_titled_nickname(user_id, group_id, nickname)
    
    # 获取今日固定运势（全局一致）
    daily = get_daily_fortune(user_id, today_date)

    def record_fortune(data: dict) -> dict:
        data.setdefault("fortune_record", {})
        data.setdefault("streak", {})

        if key in data["fortune_record"]:
            return {"already": True, "result": data["fortune_record"][key]}

        data["fortune_record"][key] = {
            "fortune": daily["fortune_name"],
            "emoji": daily["emoji"],
            "desc": daily["desc"],
            "special_event": _special_event_label(daily["special_event"]),
        }

        # 连续签到倍率
        streak_count = check_streak(data, user_id, group_id, today)
        title_bonus = roll_title_fortune_bonus(user_id, group_id, today, get_points(user_id, group_id))
        score = calculate_fortune_score(
            daily["fortune_name"],
            streak_count,
            daily["special_event"],
            title_bonus=title_bonus,
        )
        record = _build_fortune_record(today, user_id, group_id, daily, score, streak_count, award_tx_id)
        data["fortune_record"][key] = record

        return {
            "already": False,
            "record": record,
        }

    fortune_state = mutate_json(DATA_FILE, DEFAULT_FORTUNE_DATA, record_fortune)

    # 检查今天是否已经在本群抽过
    if fortune_state["already"]:
        result = fortune_state["result"]
        if (
            isinstance(result, dict)
            and result.get("points_awarded") is False
            and result.get("award_tx_id")
            and isinstance(result.get("total_points"), int)
        ):
            try:
                award_result = add_points_once(user_id, group_id, result["total_points"], result["award_tx_id"])
            except Exception as exc:
                logger.exception(f"签到积分补记失败 group_id={group_id} user_id={user_id}: {exc}")
                await matcher.finish(
                    "（拍了拍账本）今日签已在册，积分补记暂未落袋，请稍后再试。\n"
                    "『签墨未干钱未至，待风一转自归囊。』"
                )
            try:
                _mark_fortune_points_awarded(key, result["award_tx_id"])
            except Exception as exc:
                logger.exception(f"签到积分补记标记失败 group_id={group_id} user_id={user_id}: {exc}")
            point_label = "漏记补上" if award_result["applied"] else "今日已得"
            result = {**result, "points_awarded": True}
            if "poem" in result:
                await matcher.finish(
                    "『{nickname}』你今天在本群已经抽过签了！\n".format(nickname=display_name)
                    + _render_full_fortune(display_name, result, point_label=point_label)
                )

        if isinstance(result, dict) and "poem" in result:
            await matcher.finish(
                "『{nickname}』你今天在本群已经抽过签了！\n".format(nickname=display_name)
                + _render_full_fortune(display_name, result, point_label="今日已得")
            )
        await matcher.finish(_render_compact_existing_fortune(display_name, result if isinstance(result, dict) else {}))

    record = fortune_state["record"]
    total_points = record["total_points"]

    try:
        add_points_once(user_id, group_id, total_points, award_tx_id)
    except Exception as exc:
        logger.exception(f"签到积分入账失败 group_id={group_id} user_id={user_id}: {exc}")
        await matcher.finish(
            "（签已落册，账本却被风掀乱）今日签已记下，积分暂未落袋。\n"
            "稍后再输入 /签到，本猫会按原签补记。\n"
            "『签墨已成钱未至，明灯还在待君回。』"
        )
    try:
        _mark_fortune_points_awarded(key, award_tx_id)
    except Exception as exc:
        logger.exception(f"签到积分入账标记失败 group_id={group_id} user_id={user_id}: {exc}")

    unknown_notice = ""
    hidden_title_text = ""
    is_unknown_fortune = record["fortune"] == UNKNOWN_FORTUNE_NAME
    if is_unknown_fortune:
        hidden_title = grant_title(user_id, group_id, UNKNOWN_FORTUNE_TITLE_ID)
        hidden_title_text = f"\n🎖 天外名号：{hidden_title.title} 已入册" if hidden_title else ""
        unknown_notice = (
            "\n（本猫酒壶当场落地）全体看签！"
            "这不是签册翻页，这是天机掀桌。"
        )

    output = _render_full_fortune(
        display_name,
        record,
        hidden_title_text=hidden_title_text,
        prefix_text=unknown_notice,
    )

    if is_unknown_fortune:
        await matcher.finish(MessageSegment.at("all") + MessageSegment.text("\n" + output))

    await matcher.finish(output)


@fortune.handle()
async def handle_fortune(bot: Bot, event: MessageEvent):
    await send_fortune(fortune, bot, event)


@fortune_plain.handle()
async def handle_plain_fortune(bot: Bot, event: MessageEvent):
    await send_fortune(fortune_plain, bot, event)


makeup = on_command("补签", priority=5, block=True)


@makeup.handle()
async def handle_makeup(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await makeup.finish(
            "（合上签册）补签请在群里使用。\n"
            "『群中签册群中补，独坐空房墨不留。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    plan = get_makeup_plan(user_id, group_id)
    operation_service = PaidOperationService()

    if plan["status"] == "none":
        await makeup.finish(
            "（翻遍今年签册）近前没有可补的空页。\n"
            "『签路若已无断墨，且把今日好好书。』"
        )

    if plan["status"] == "limited":
        await makeup.finish(
            f"（停笔望旧岁）阁下在本群的历史最长连签为 {plan['historical_longest']} 天，"
            f"只补今年旧页最多可续至 {plan['restored_streak']} 天，尚无法恢复。\n"
            "本猫不收这笔墨资；今日若未签到，可先落今日一签，待可恢复时再来。"
        )

    if plan["status"] == "already":
        await makeup.finish(
            f"（翻开签册）{plan['target_date']} 已有签到记录，无需补签。\n"
            f"『旧页墨痕分明在，何须今日再重描。』"
        )

    points_info = get_points(user_id, group_id)
    cost = plan["cost"]
    if points_info["current"] < cost:
        await makeup.finish(
            f"（拨算盘）这是本年度第 {plan['next_count']} 次补签，需 {cost} 积分。\n"
            f"阁下当前只有 {points_info['current']} 积分，暂时补不起。\n"
            f"『囊中墨钱尚不足，且待签到攒几回。』"
        )

    request_key = _makeup_request_key(plan)
    pending = operation_service.find_open(
        feature_key="fortune",
        user_id=user_id,
        group_id=group_id,
    )
    if pending is not None:
        if pending.status != OPERATION_AWAITING_CONFIRMATION:
            await makeup.finish(paid_operation_processing_message())
        stored_operation = pending.record.get("payload", {}).get("paid_operation", {})
        if stored_operation.get("request_fingerprint") != request_fingerprint(request_key):
            try:
                operation_service.refund(pending.operation_id, reason="makeup_plan_changed")
            except Exception as exc:
                logger.exception(f"补签旧确认撤销失败 operation_id={pending.operation_id}: {exc}")
                await makeup.finish("（按住旧签页）前一笔确认尚在核对，请稍后再来。")
            pending = None

    if pending is None:
        try:
            operation = operation_service.begin(
                feature_key="fortune",
                user_id=user_id,
                group_id=group_id,
                cost=cost,
                request_key=request_key,
                confirmation_required=True,
                ttl_seconds=MAKEUP_CONFIRM_TTL_SECONDS,
            )
        except Exception as exc:
            logger.exception(f"补签确认落册失败 user_id={user_id} group_id={group_id}: {exc}")
            await makeup.finish("（签册被风掀乱）这笔确认暂未落稳，请稍后再试。")
        await makeup.finish(
            f"📜 李太白给·补签确认 📜\n"
            f"{'='*20}\n"
            f"（翻回旧页）这一笔若要补上，先把账与时辰说明白。\n"
            f"{'='*20}\n"
            f"补签日期：{_fortune_storage.format_makeup_dates(plan['target_dates'])}\n"
            f"本次共补：{len(plan['target_dates'])} 天（仅限本年度旧日）\n"
            f"本群历史最长：{plan['historical_longest']} 天；补后连续签到：{plan['restored_streak']} 天\n"
            f"本年第 {plan['next_count']} 次补签\n"
            f"整次所需积分：{cost}（只计一次，首次 10，之后每次翻倍）\n"
            f"{'='*20}\n"
            f"补签只修复连续天数，不补发旧日积分，今日已入账积分也不重算。\n"
            f"今日若未签到，本次连签以昨日为止，今日仍需自行落签。\n"
            f"60 秒内再次输入 /补签 确认。\n"
            f"『旧页断墨今重续，数日空白一笔填。清账只收一回资，长风再伴签路前。』"
        )

    if pending.status != OPERATION_AWAITING_CONFIRMATION:
        await makeup.finish(paid_operation_processing_message())
    try:
        operation = operation_service.confirm(pending.operation_id)
    except PaidOperationExpired:
        await makeup.finish(
            "（合上旧签页）方才的确认已经过时，请重新输入 /补签。\n"
            "『一盏风过旧时限，重翻此页再题名。』"
        )
    except PaidOperationInsufficientBalance as exc:
        await makeup.finish(
            f"（拨算盘）确认时账上只余 {exc.balance} 积分，这一笔暂补不起。\n"
            "『囊中墨钱尚不足，且待签到攒几回。』"
        )
    except Exception as exc:
        logger.exception(f"补签确认扣费失败 operation_id={pending.operation_id}: {exc}")
        await makeup.finish(
            "（算盘一停）这笔补签墨资暂时落不了账，请重新查看后再试。\n"
            "『算盘偶有珠声乱，稍候重来墨自安。』"
        )

    if operation.existing:
        await makeup.finish(paid_operation_processing_message())

    try:
        result = _apply_makeup(user_id, group_id, cost, request_key)
    except Exception as exc:
        logger.exception(f"补签写入失败 group_id={group_id} user_id={user_id}: {exc}")
        try:
            operation_service.refund(operation.operation_id, reason="makeup_write_failed")
        except Exception as refund_exc:
            logger.exception(f"补签退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await makeup.finish("（墨迹洇开）旧页未成，账页尚在核对，请勿重复落签。")
        await makeup.finish(paid_operation_refund_message(cost))

    if result["status"] != "created":
        try:
            operation_service.refund(operation.operation_id, reason=f"makeup_{result['status']}")
        except Exception as refund_exc:
            logger.exception(f"补签状态退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await makeup.finish("（按住签册）旧页状态有变，账页尚在核对，请勿重复落签。")
        if result["status"] == "none":
            await makeup.finish(
                "（翻遍今年签册）近前没有可补的空页，本次积分已退回。\n"
                "『签路若已无断墨，且把今日好好书。』"
            )
        if result["status"] == "already":
            await makeup.finish(
                "（翻开签册）这页已经补过或签过，本次积分已退回。\n"
                "『旧页已有清清字，不劳今朝再费钱。』"
            )
        await makeup.finish(
            "（拨回算盘）签册或费用已有变化，本次积分已退回，请重新输入 /补签 查看。\n"
            "『旧页风翻须再看，重问一声再落签。』"
        )

    try:
        operation_service.complete(
            operation.operation_id,
            result_key=f"{result['target_date']}:{result['next_count']}:{result['streak_count']}",
        )
    except Exception as exc:
        logger.exception(f"补签结账失败 operation_id={operation.operation_id}: {exc}")
        try:
            current = operation_service.get(operation.operation_id)
        except Exception as status_exc:
            logger.exception(f"补签状态核对失败 operation_id={operation.operation_id}: {status_exc}")
            await makeup.finish("（按住新墨）旧页已经补妥，账页尚未干透，请勿重复落签。")
        if current.status != OPERATION_COMPLETED:
            await makeup.finish("（按住新墨）旧页已经补妥，账页尚未干透，请勿重复落签。")

    nickname = await get_nickname(bot, user_id, context="补签")
    display_name = _format_titled_nickname(user_id, group_id, nickname)
    today_record_text = "今日签面：已同步补签后的连续天数\n" if result.get("today_record_repaired") else ""
    await makeup.finish(
        f"📜 补签成功 📜\n"
        f"{'='*20}\n"
        f"（提笔补完旧页）这一行总算续上，签路又顺了一截。\n"
        f"{'='*20}\n"
        f"人物：{display_name}\n"
        f"补签日期：{_fortune_storage.format_makeup_dates(result['target_dates'])}\n"
        f"本次共补：{len(result['target_dates'])} 天\n"
        f"整次花费：{cost} 积分（只计一次）\n"
        f"本年度已补签：{result['next_count']} 次\n"
        f"补前历史最长：{result['historical_longest']} 天\n"
        f"当前连续签到：{result['streak_count']} 天\n"
        f"{today_record_text}"
        f"旧日积分不补发，今日已入账积分不重算；今日未签仍须自行落签。\n"
        f"{'='*20}\n"
        f"『旧页墨痕今补上，续得签路又一章。』"
    )

# 调试命令
debug_fortune = on_command("debug 运势", aliases={"debug运势", "调试运势"}, priority=3, block=True)


def _resolve_debug_fortune_group(event: MessageEvent, raw_text: str) -> str | None:
    requested_group_id = raw_text.strip()
    if requested_group_id:
        try:
            return normalize_id(requested_group_id, "group_id")
        except ValueError:
            return None
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


@debug_fortune.handle()
async def handle_debug_fortune(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
):
    user_id = event.get_user_id()
    if not is_admin_user(user_id):
        await debug_fortune.finish(
            "（把试签藏回袖中）此签只给掌柜验墨。\n"
            "『闲人莫翻炉中火，免把天机试成灰。』"
        )

    group_id = _resolve_debug_fortune_group(event, args.extract_plain_text())
    if group_id is None:
        await debug_fortune.finish(
            "（收起试签）用法：/debug 运势 [群号]\n"
            "『签筒若离群中响，须把群号写成章。』"
        )

    nickname = await get_nickname(bot, user_id, context="调试运势")
    display_name = _format_titled_nickname(user_id, group_id, nickname)
    
    # 获取今日固定运势
    daily = get_daily_fortune(user_id, current_date())
    
    # 计算积分
    streak_count = get_current_streak(user_id, group_id)
    title_bonus = roll_title_fortune_bonus(
        user_id,
        group_id,
        current_date().strftime("%Y-%m-%d"),
        get_points(user_id, group_id),
    )
    score = calculate_fortune_score(
        daily["fortune_name"],
        streak_count,
        daily["special_event"],
        title_bonus=title_bonus,
    )
    special_text = score["special_text"]
    title_power_text = score["title_power_text"]
    
    # 构建输出
    output = f"""🛠 【试签模式】今日运势签 🛠
{'='*20}
✦ {display_name} の运势 ✦
{'='*20}
【运势】{daily['fortune_name']} {daily['emoji']}{special_text}
【解读】{daily['desc']}
{'='*20}
🔢 幸运数字：{daily['lucky_number']}
🎨 幸运颜色：{daily['lucky_color']}
✅ 宜：{' / '.join(daily['yi'])}
❌ 忌：{' / '.join(daily['ji'])}
{'='*20}
📜 诗人曰：
{daily['poet_comment']}

『{daily['poem']}』
{'='*20}
🔥 当前连续签到 {streak_count} 天
💰 本次积分 {score['total_points']}（试签不入账）{title_power_text}"""

    try:
        record_admin_action(
            actor_user_id=user_id,
            action="debug_fortune_view",
            scope="group",
            source_group_id=str(event.group_id) if isinstance(event, GroupMessageEvent) else None,
            target_group_id=group_id,
            details={"command": "debug 运势"},
        )
    except Exception as exc:
        logger.exception("管理员审计落盘失败 action=debug_fortune_view: %s", exc)
        output += "\n（封印簿未能落印，请系统掌柜即刻查看 /系统诊断。）"

    await debug_fortune.finish(output)
