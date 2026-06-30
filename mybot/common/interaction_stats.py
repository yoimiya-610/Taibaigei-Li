from pathlib import Path
from datetime import datetime

from mybot.common.json_store import load_json, mutate_json


STATS_FILE = Path(__file__).resolve().parent.parent / "data" / "interaction_stats.json"


def _stat_key(group_id: str, user_id: str) -> str:
    return f"{group_id}_{user_id}"


def add_auto_reply_trigger(user_id: str, group_id: str) -> int:
    key = _stat_key(group_id, user_id)
    month = datetime.now().strftime("%Y-%m")

    def mutator(data: dict) -> int:
        auto_replies = data.setdefault("auto_replies", {})
        record = auto_replies.setdefault(
            key,
            {"user_id": user_id, "group_id": group_id, "count": 0},
        )
        record["count"] = int(record.get("count", 0)) + 1
        monthly_records = data.setdefault("monthly_auto_replies", {}).setdefault(month, {})
        monthly_record = monthly_records.setdefault(
            key,
            {"user_id": user_id, "group_id": group_id, "count": 0},
        )
        monthly_record["count"] = int(monthly_record.get("count", 0)) + 1
        return int(record["count"])

    return mutate_json(STATS_FILE, {}, mutator)


def get_auto_reply_trigger_count(user_id: str, group_id: str) -> int:
    key = _stat_key(group_id, user_id)
    data = load_json(STATS_FILE, {})
    record = data.get("auto_replies", {}).get(key, {})
    try:
        return int(record.get("count", 0))
    except (TypeError, ValueError):
        return 0


def get_monthly_auto_reply_counts(group_id: str, month: str) -> dict[str, int]:
    data = load_json(STATS_FILE, {})
    records = data.get("monthly_auto_replies", {}).get(month, {})
    result = {}
    if not isinstance(records, dict):
        return result
    for record in records.values():
        if not isinstance(record, dict):
            continue
        if str(record.get("group_id")) != group_id:
            continue
        user_id = str(record.get("user_id") or "")
        if not user_id:
            continue
        try:
            result[user_id] = int(record.get("count", 0))
        except (TypeError, ValueError):
            result[user_id] = 0
    return result
