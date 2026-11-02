"""Fortune record lookups and idempotent persistence updates."""

from datetime import date, timedelta
from pathlib import Path

from mybot.common.json_store import mutate_json
from mybot.common.streak import (
    DEFAULT_FORTUNE_DATA,
    calculate_longest_streak,
    has_signed_on as _has_signed_on,
)

def _makeup_usage_key(year: int, user_id: str, group_id: str) -> str:
    return f"{year}_{group_id}_{user_id}"



def _find_makeup_target_date(data: dict, user_id: str, group_id: str, today_date: date) -> str:
    year_start = today_date.replace(month=1, day=1)
    cursor = today_date - timedelta(days=1)
    while cursor >= year_start:
        date_text = cursor.strftime("%Y-%m-%d")
        if not _has_signed_on(data, user_id, group_id, date_text):
            return date_text
        cursor -= timedelta(days=1)
    return ""


def plan_makeup_dates(data: dict, user_id: str, group_id: str, today_date: date) -> dict:
    """补最近断档，必要时继续往前，直至恢复历史纪录；不跨年填空。"""
    longest = calculate_longest_streak(data, user_id, group_id, today_date)
    year_start = today_date.replace(month=1, day=1)
    cursor = today_date
    if not _has_signed_on(data, user_id, group_id, cursor.isoformat()):
        cursor -= timedelta(days=1)
    count = 0
    dates = []
    while True:
        if _has_signed_on(data, user_id, group_id, cursor.isoformat()):
            count += 1
            cursor -= timedelta(days=1)
            continue
        if dates and count >= longest:
            status = "available"
            break
        if cursor < year_start:
            status = "limited" if count < longest else "none"
            break
        dates.append(cursor.isoformat())
        count += 1
        cursor -= timedelta(days=1)
    return {
        "status": status,
        "target_dates": sorted(dates),
        "historical_longest": longest,
        "restored_streak": count,
    }


def format_makeup_dates(dates: list[str]) -> str:
    """合并相邻补签日，避免把已有签到日误报为本次补签。"""
    ranges = []
    start = end = dates[0]
    for date_text in dates[1:]:
        if date.fromisoformat(date_text) - date.fromisoformat(end) == timedelta(days=1):
            end = date_text
        else:
            ranges.append(start if start == end else f"{start} 至 {end}")
            start = end = date_text
    ranges.append(start if start == end else f"{start} 至 {end}")
    return "、".join(ranges)



def mark_fortune_points_awarded(data_file: Path, key: str, award_tx_id: str) -> None:
    def mutator(data: dict) -> None:
        record = data.setdefault("fortune_record", {}).get(key)
        if isinstance(record, dict) and record.get("award_tx_id") == award_tx_id:
            record["points_awarded"] = True

    mutate_json(data_file, DEFAULT_FORTUNE_DATA, mutator)
