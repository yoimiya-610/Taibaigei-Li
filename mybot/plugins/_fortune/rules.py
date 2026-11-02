"""Pure streak and fortune scoring rules."""

from datetime import datetime

from mybot.common.streak import sync_streak as _sync_streak

from .copy import (
    FORTUNE_POINTS,
    MIN_MAKEUP_COST,
    STREAK_MULTIPLIER_CAP_DAY,
    STREAK_MULTIPLIER_MAX_TENTHS,
    STREAK_MULTIPLIER_MIN_TENTHS,
    STREAK_MULTIPLIER_START_DAY,
    UNKNOWN_FORTUNE_NAME,
)

def calculate_makeup_cost(makeup_count: int) -> int:
    return MIN_MAKEUP_COST * (2 ** max(makeup_count - 1, 0))



def check_streak(data, user_id, group_id, today):
    """兼容旧调用：按签到和补签记录重新计算连续签到。"""
    return _sync_streak(data, user_id, group_id, datetime.strptime(today, "%Y-%m-%d").date())

def get_streak_bonus(streak_count: int, base_points: int = 0) -> int:
    """兼容旧调用：返回连续签到倍率相比基础分额外增加的积分。"""
    if base_points <= 0:
        return 0
    multiplier_tenths = get_streak_multiplier_tenths(streak_count)
    return apply_streak_multiplier(base_points, multiplier_tenths) - base_points


def get_streak_multiplier_tenths(streak_count: int) -> int:
    """3 至 365 天按 0.1 档线性提升，从 x1.1 到 x3。"""
    if streak_count < STREAK_MULTIPLIER_START_DAY:
        return 10
    if streak_count >= STREAK_MULTIPLIER_CAP_DAY:
        return STREAK_MULTIPLIER_MAX_TENTHS

    span_days = STREAK_MULTIPLIER_CAP_DAY - STREAK_MULTIPLIER_START_DAY
    span_tenths = STREAK_MULTIPLIER_MAX_TENTHS - STREAK_MULTIPLIER_MIN_TENTHS
    progressed_days = streak_count - STREAK_MULTIPLIER_START_DAY
    rounded_steps = (progressed_days * span_tenths * 2 + span_days) // (span_days * 2)
    return STREAK_MULTIPLIER_MIN_TENTHS + rounded_steps


def apply_streak_multiplier(points: int, multiplier_tenths: int) -> int:
    return (points * multiplier_tenths + 5) // 10


def format_streak_multiplier(multiplier_tenths: int) -> str:
    text = f"{multiplier_tenths / 10:.1f}"
    return text.rstrip("0").rstrip(".")


def calculate_fortune_score(
    fortune_name: str,
    streak_count: int,
    special_event: dict | None = None,
    title_bonus: dict | None = None,
) -> dict:
    base_points = FORTUNE_POINTS[fortune_name]
    streak_multiplier = 10 if fortune_name == UNKNOWN_FORTUNE_NAME else get_streak_multiplier_tenths(streak_count)
    total_points = base_points if fortune_name == UNKNOWN_FORTUNE_NAME else apply_streak_multiplier(base_points, streak_multiplier)
    special_text = ""
    if fortune_name != UNKNOWN_FORTUNE_NAME and special_event:
        if special_event["name"] == "🌈 好运加倍":
            total_points *= 2
        else:
            total_points += special_event["points"]
        special_text = f"\n✨ 特殊事件：{special_event['name']}（{special_event['desc']}）"
    title_power_text = ""
    if title_bonus and title_bonus.get("activated"):
        total_points *= 2
        title_power_text = (
            f"\n🎖 称号之力：使用了“{title_bonus['title']}”的力量，积分翻倍"
            f"（{title_bonus['rarity']}，触发率 {title_bonus['trigger_rate']}%）"
        )

    return {
        "base_points": base_points,
        "streak_multiplier": streak_multiplier,
        "total_points": total_points,
        "special_text": special_text,
        "title_power_text": title_power_text,
        "title_bonus": dict(title_bonus or {}),
    }


def _special_event_label(special_event: dict | None) -> str | None:
    if not special_event:
        return None
    return f"{special_event['name']}（{special_event['desc']}）"


def _award_tx_id(key: str) -> str:
    return f"fortune:{key}"
