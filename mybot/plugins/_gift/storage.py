"""Daily flower reservation persistence."""

from datetime import datetime
from pathlib import Path

from mybot.common.json_store import mutate_json

from .copy import FLOWER_TIERS


def daily_flower_key(group_id: str, user_id: str) -> str:
    return f"{group_id}_{user_id}"


def reserve_daily_flower(
    group_id: str,
    user_id: str,
    target_id: str,
    amount: int,
    *,
    data_file: Path,
    now: datetime | None = None,
) -> dict | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    key = daily_flower_key(group_id, user_id)

    def mutator(data: dict) -> dict | None:
        sent = data.setdefault("sent", {})
        previous = sent.get(key)
        if isinstance(previous, dict) and previous.get("date") == today:
            return dict(previous)
        sent[key] = {
            "date": today,
            "target_id": target_id,
            "amount": amount,
            "gift": FLOWER_TIERS[amount]["name"],
            "reward": FLOWER_TIERS[amount]["reward"],
            "charm": FLOWER_TIERS[amount]["charm"],
            "timestamp": current.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return None

    return mutate_json(data_file, {}, mutator)


def release_daily_flower(group_id: str, user_id: str, amount: int, *, data_file: Path) -> None:
    key = daily_flower_key(group_id, user_id)

    def mutator(data: dict) -> None:
        sent = data.setdefault("sent", {})
        current = sent.get(key)
        if isinstance(current, dict) and current.get("amount") == amount:
            sent.pop(key, None)

    mutate_json(data_file, {}, mutator)
