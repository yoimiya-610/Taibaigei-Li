from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mybot.common.json_store import load_json, save_json


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "fortune_data.json"
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_FORTUNE_DATA = {
    "fortune_record": {},
    "streak": {},
    "makeup_records": {},
    "makeup_usage": {},
}


def load_data() -> dict:
    return load_json(DATA_FILE, DEFAULT_FORTUNE_DATA)


def save_data(data: dict) -> None:
    save_json(DATA_FILE, data)


def streak_key(user_id: str, group_id: str) -> str:
    return f"{group_id}_{user_id}"


def fortune_record_key(date_text: str, user_id: str, group_id: str) -> str:
    return f"{date_text}_{group_id}_{user_id}"


def has_signed_on(data: dict, user_id: str, group_id: str, date_text: str) -> bool:
    fortune_records = data.get("fortune_record", {})
    if fortune_record_key(date_text, user_id, group_id) in fortune_records:
        return True

    makeup_records = data.get("makeup_records", {})
    user_records = makeup_records.get(streak_key(user_id, group_id), {})
    return date_text in user_records.get("dates", [])


def calculate_current_streak(
    data: dict,
    user_id: str,
    group_id: str,
    today_date: date | None = None,
) -> int:
    """按实际签到和补签日期计算当前连续签到天数。"""
    today_date = today_date or datetime.now(APP_TIMEZONE).date()
    cursor = today_date

    if not has_signed_on(data, user_id, group_id, cursor.strftime("%Y-%m-%d")):
        cursor -= timedelta(days=1)
        if not has_signed_on(data, user_id, group_id, cursor.strftime("%Y-%m-%d")):
            return 0

    count = 0
    while has_signed_on(data, user_id, group_id, cursor.strftime("%Y-%m-%d")):
        count += 1
        cursor -= timedelta(days=1)
    return count


def sync_streak(
    data: dict,
    user_id: str,
    group_id: str,
    today_date: date | None = None,
) -> int:
    today_date = today_date or datetime.now(APP_TIMEZONE).date()
    count = calculate_current_streak(data, user_id, group_id, today_date)
    today_text = today_date.strftime("%Y-%m-%d")
    yesterday_text = (today_date - timedelta(days=1)).strftime("%Y-%m-%d")

    if has_signed_on(data, user_id, group_id, today_text):
        last_date = today_text
    elif has_signed_on(data, user_id, group_id, yesterday_text):
        last_date = yesterday_text
    else:
        last_date = ""

    data.setdefault("streak", {})[streak_key(user_id, group_id)] = {
        "count": count,
        "last_date": last_date,
    }
    return count


def get_current_streak(user_id: str, group_id: str) -> int:
    return calculate_current_streak(load_data(), user_id, group_id)


def get_streak_evaluation(streak_count: int) -> str:
    if streak_count >= 365:
        return "岁岁不辍，签到已成阁下的日常修行。"
    if streak_count >= 100:
        return "百日不断，恒心已足以让本猫肃然起敬。"
    if streak_count >= 30:
        return "一月不辍，阁下这份坚持颇有长风之势。"
    if streak_count >= 7:
        return "七日成章，签到习惯已经渐入佳境。"
    if streak_count >= 3:
        return "三日连签，小小坚持正在生根。"
    if streak_count >= 1:
        return "签册已有一笔，下一日莫让墨迹断了。"
    return "签路尚空，今日落下第一笔也不迟。"
