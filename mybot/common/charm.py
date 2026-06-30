from pathlib import Path
from datetime import datetime

from mybot.common.json_store import load_json, mutate_json


CHARM_FILE = Path(__file__).resolve().parent.parent / "data" / "charm.json"


def _charm_key(group_id: str, user_id: str) -> str:
    return f"{group_id}_{user_id}"


def change_charm(user_id: str, group_id: str, amount: int) -> dict:
    key = _charm_key(group_id, user_id)
    month = datetime.now().strftime("%Y-%m")

    def mutator(data: dict) -> dict:
        records = data.setdefault("records", {})
        record = records.setdefault(
            key,
            {"user_id": user_id, "group_id": group_id, "charm": 0},
        )
        record["charm"] = max(0, int(record.get("charm", 0)) + amount)
        if amount != 0:
            monthly_records = data.setdefault("monthly", {}).setdefault(month, {})
            monthly_record = monthly_records.setdefault(
                key,
                {"user_id": user_id, "group_id": group_id, "charm": 0},
            )
            monthly_record["charm"] = max(0, int(monthly_record.get("charm", 0)) + amount)
        return dict(record)

    return mutate_json(CHARM_FILE, {}, mutator)


def get_charm(user_id: str, group_id: str) -> int:
    key = _charm_key(group_id, user_id)
    data = load_json(CHARM_FILE, {})
    record = data.get("records", {}).get(key, {})
    try:
        return int(record.get("charm", 0))
    except (TypeError, ValueError):
        return 0


def get_group_charm_ranking(group_id: str, limit: int = 10) -> list[dict]:
    data = load_json(CHARM_FILE, {})
    records = [
        dict(record)
        for record in data.get("records", {}).values()
        if str(record.get("group_id")) == group_id and int(record.get("charm", 0)) > 0
    ]
    records.sort(key=lambda record: int(record.get("charm", 0)), reverse=True)
    return records[:limit]


def get_monthly_charm_gains(group_id: str, month: str) -> dict[str, int]:
    data = load_json(CHARM_FILE, {})
    records = data.get("monthly", {}).get(month, {})
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
            result[user_id] = int(record.get("charm", 0))
        except (TypeError, ValueError):
            result[user_id] = 0
    return result
