from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from mybot.common.feature_flags import is_feature_enabled
from mybot.common.json_store import load_json, mutate_json


BOT_ROOT = Path(__file__).resolve().parent.parent
ESSENCE_FILE = BOT_ROOT / "data" / "group_essence.json"
MESSAGE_FILE = BOT_ROOT / "data" / "group_message_index.json"
CARD_FILE = BOT_ROOT / "data" / "group_card_sync.json"
CARD_QUEUE_FILE = BOT_ROOT / "data" / "group_card_queue.json"
ACTIVITY_FILE = BOT_ROOT / "data" / "group_activities.json"
ACTIVITY_ARCHIVE_FILE = BOT_ROOT / "data" / "group_activity_archive.json"
DEFAULT_GROUPS = {"version": 1, "groups": {}}
MAX_INDEX_MESSAGES = 500
MAX_CARD_LENGTH = 60
CARD_COOLDOWN_SECONDS = 60
POKE_COOLDOWN_SECONDS = 30
LIKE_CANDIDATE_THRESHOLD = 3
REPLY_CANDIDATE_THRESHOLD = 2
ALLOWED_CARD_TOKENS = {"{title}", "{nickname}"}


def now_text(now: datetime | None = None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


def clean_summary(text: str, limit: int = 180) -> str:
    value = "".join(char for char in str(text) if char in "\t " or unicodedata.category(char)[0] != "C")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def index_message(
    group_id: str,
    message_id: str,
    user_id: str,
    nickname: str,
    text: str,
    reply_to: str | None,
    timestamp: int | float | None,
) -> None:
    record = {
        "message_id": str(message_id),
        "user_id": str(user_id),
        "nickname": clean_summary(nickname, 60),
        "text": clean_summary(text),
        "reply_to": str(reply_to) if reply_to else "",
        "timestamp": int(timestamp or datetime.now().timestamp()),
    }

    def mutator(data: dict) -> None:
        messages = data.setdefault("groups", {}).setdefault(str(group_id), {}).setdefault("messages", [])
        messages[:] = [item for item in messages if str(item.get("message_id")) != str(message_id)]
        messages.append(record)
        del messages[:-MAX_INDEX_MESSAGES]

    mutate_json(MESSAGE_FILE, DEFAULT_GROUPS, mutator)


def record_emoji_likes(group_id: str, message_id: str, likes: Any) -> None:
    count = 0
    if isinstance(likes, list):
        count = sum(max(0, int(item.get("count", 0))) for item in likes if isinstance(item, dict))

    def mutator(data: dict) -> None:
        group = data.setdefault("groups", {}).setdefault(str(group_id), {})
        group.setdefault("likes", {})[str(message_id)] = count

    mutate_json(ESSENCE_FILE, DEFAULT_GROUPS, mutator)


def sync_essence_event(
    group_id: str,
    message_id: str,
    subtype: str,
    sender_id: str = "",
    operator_id: str = "",
) -> None:
    def mutator(data: dict) -> None:
        group = data.setdefault("groups", {}).setdefault(str(group_id), {})
        index = group.setdefault("index", {})
        record = index.setdefault(str(message_id), {})
        record.update(
            {
                "message_id": str(message_id),
                "sender_id": str(sender_id),
                "operator_id": str(operator_id),
                "active": subtype == "add",
                "updated_at": now_text(),
            }
        )
        group.setdefault("pending", {}).pop(str(message_id), None)

    mutate_json(ESSENCE_FILE, DEFAULT_GROUPS, mutator)


def mark_essence_pending(group_id: str, message_id: str, operation: str) -> None:
    def mutator(data: dict) -> None:
        group = data.setdefault("groups", {}).setdefault(str(group_id), {})
        group.setdefault("pending", {})[str(message_id)] = {
            "operation": operation,
            "updated_at": now_text(),
        }

    mutate_json(ESSENCE_FILE, DEFAULT_GROUPS, mutator)


def clear_essence_pending(group_id: str, message_id: str) -> None:
    def mutator(data: dict) -> None:
        group = data.setdefault("groups", {}).setdefault(str(group_id), {})
        group.setdefault("pending", {}).pop(str(message_id), None)

    mutate_json(ESSENCE_FILE, DEFAULT_GROUPS, mutator)


def build_candidates(group_id: str, limit: int = 10) -> list[dict]:
    messages = load_json(MESSAGE_FILE, DEFAULT_GROUPS).get("groups", {}).get(str(group_id), {}).get("messages", [])
    essence = load_json(ESSENCE_FILE, DEFAULT_GROUPS).get("groups", {}).get(str(group_id), {})
    active = {
        key for key, value in essence.get("index", {}).items()
        if isinstance(value, dict) and value.get("active")
    }
    likes = essence.get("likes", {}) if isinstance(essence.get("likes"), dict) else {}
    reply_counts: dict[str, int] = {}
    for item in messages:
        reply_to = str(item.get("reply_to") or "")
        if reply_to:
            reply_counts[reply_to] = reply_counts.get(reply_to, 0) + 1
    candidates = []
    for item in messages:
        message_id = str(item.get("message_id", ""))
        if not message_id or message_id in active or not item.get("text"):
            continue
        like_value = likes.get(message_id)
        candidate = dict(item)
        candidate["likes"] = int(like_value) if isinstance(like_value, int) else None
        candidate["replies"] = reply_counts.get(message_id, 0)
        candidate["reply_coverage"] = "observed"
        candidate["qualified"] = (
            (candidate["likes"] is not None and candidate["likes"] >= LIKE_CANDIDATE_THRESHOLD)
            or candidate["replies"] >= REPLY_CANDIDATE_THRESHOLD
        )
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            item["likes"] if item["likes"] is not None else -1,
            item["replies"],
            item["timestamp"],
            item["message_id"],
        ),
        reverse=True,
    )
    qualified = [item for item in candidates if item["qualified"]]
    # If no message crosses a reliably observed threshold, expose a clearly
    # labelled recent fallback instead of inventing unavailable interaction data.
    selected = qualified or candidates
    for item in selected:
        item["candidate_mode"] = "threshold" if qualified else "recent_fallback"
    return selected[:limit]


def weekly_digest(group_id: str, now: datetime | None = None) -> list[dict]:
    cutoff = int(((now or datetime.now()) - timedelta(days=7)).timestamp())
    return [item for item in build_candidates(group_id, 50) if int(item.get("timestamp", 0)) >= cutoff][:10]


def normalize_card_format(value: str) -> str:
    text = clean_summary(value, 80).replace("【称号】", "{title}").replace("昵称", "{nickname}")
    tokens = set(re.findall(r"\{[^{}]*\}", text))
    if not text or not tokens.issubset(ALLOWED_CARD_TOKENS) or "{nickname}" not in text:
        raise ValueError("invalid_card_format")
    return text


def render_card(format_text: str, title: str, nickname: str) -> str:
    card = format_text.format(title=clean_summary(title, 30), nickname=clean_summary(nickname, 40))
    card = re.sub(r"[\[\]{}<>\\\r\n]", "", card)
    card = clean_summary(card, MAX_CARD_LENGTH)
    if not card:
        raise ValueError("empty_card")
    return card


def authorize_card(group_id: str, user_id: str, original_card: str, nickname: str, format_text: str) -> dict:
    normalized = normalize_card_format(format_text)

    def mutator(data: dict) -> dict:
        users = data.setdefault("groups", {}).setdefault(str(group_id), {}).setdefault("users", {})
        record = users.setdefault(str(user_id), {})
        if "original_card" not in record:
            record["original_card"] = str(original_card or "")
        record.update({"enabled": True, "nickname": clean_summary(nickname, 40), "format": normalized})
        return dict(record)

    return mutate_json(CARD_FILE, DEFAULT_GROUPS, mutator)


def get_card_record(group_id: str, user_id: str) -> dict | None:
    record = load_json(CARD_FILE, DEFAULT_GROUPS).get("groups", {}).get(str(group_id), {}).get("users", {}).get(str(user_id))
    return dict(record) if isinstance(record, dict) else None


def disable_card(group_id: str, user_id: str) -> dict | None:
    def mutator(data: dict) -> dict | None:
        record = data.setdefault("groups", {}).setdefault(str(group_id), {}).setdefault("users", {}).get(str(user_id))
        if not isinstance(record, dict):
            return None
        record["enabled"] = False
        return dict(record)

    result = mutate_json(CARD_FILE, DEFAULT_GROUPS, mutator)
    remove_card_job(group_id, user_id)
    return result


def queue_card_sync(group_id: str, user_id: str, due_at: datetime | None = None) -> bool:
    if not is_feature_enabled("group_admin_assistant", group_id):
        return False
    record = get_card_record(group_id, user_id)
    if not record or not record.get("enabled"):
        return False
    due = due_at or datetime.now() + timedelta(seconds=CARD_COOLDOWN_SECONDS)

    def mutator(data: dict) -> None:
        data.setdefault("jobs", {})[f"{group_id}:{user_id}"] = {
            "group_id": str(group_id), "user_id": str(user_id),
            "due_at": now_text(due), "attempts": 0,
        }

    mutate_json(CARD_QUEUE_FILE, {"version": 1, "jobs": {}}, mutator)
    return True


def remove_card_job(group_id: str, user_id: str) -> None:
    mutate_json(
        CARD_QUEUE_FILE,
        {"version": 1, "jobs": {}},
        lambda data: data.setdefault("jobs", {}).pop(f"{group_id}:{user_id}", None),
    )


def due_card_jobs(now: datetime | None = None) -> list[dict]:
    current = now or datetime.now()
    jobs = load_json(CARD_QUEUE_FILE, {"version": 1, "jobs": {}}).get("jobs", {})
    due = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        try:
            due_at = datetime.fromisoformat(str(job["due_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if due_at <= current:
            due.append(dict(job))
    return due


def retry_card_job(group_id: str, user_id: str) -> None:
    def mutator(data: dict) -> None:
        job = data.setdefault("jobs", {}).get(f"{group_id}:{user_id}")
        if not isinstance(job, dict):
            return
        job["attempts"] = int(job.get("attempts", 0)) + 1
        delay = min(3600, 60 * (2 ** min(job["attempts"], 6)))
        job["due_at"] = now_text(datetime.now() + timedelta(seconds=delay))

    mutate_json(CARD_QUEUE_FILE, {"version": 1, "jobs": {}}, mutator)


_poke_times: dict[tuple[str, str], datetime] = {}


def allow_poke(group_id: str, operator_id: str, now: datetime | None = None) -> bool:
    current = now or datetime.now()
    key = (str(group_id), str(operator_id))
    previous = _poke_times.get(key)
    if previous and (current - previous).total_seconds() < POKE_COOLDOWN_SECONDS:
        return False
    _poke_times[key] = current
    return True


def create_activity(group_id: str, creator_id: str, name: str, now: datetime | None = None) -> dict:
    clean_name = clean_summary(name, 40)
    if not clean_name:
        raise ValueError("missing_name")

    def mutator(data: dict) -> dict:
        group = data.setdefault("groups", {}).setdefault(str(group_id), {})
        current = group.get("current")
        if isinstance(current, dict) and current.get("status") == "active":
            raise ValueError("activity_exists")
        activity_id = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
        activity = {
            "id": activity_id, "name": clean_name, "creator_id": str(creator_id),
            "status": "active", "created_at": now_text(now), "participants": {},
            "chain": [], "deadline": "", "seed": "",
        }
        group["current"] = activity
        return dict(activity)

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def get_activity(group_id: str) -> dict | None:
    value = load_json(ACTIVITY_FILE, DEFAULT_GROUPS).get("groups", {}).get(str(group_id), {}).get("current")
    return dict(value) if isinstance(value, dict) else None


def join_activity(group_id: str, user_id: str, nickname: str) -> int:
    def mutator(data: dict) -> int:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict) or current.get("status") != "active":
            raise ValueError("no_activity")
        current.setdefault("participants", {})[str(user_id)] = clean_summary(nickname, 40)
        return len(current["participants"])

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def leave_activity(group_id: str, user_id: str) -> int:
    def mutator(data: dict) -> int:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict):
            raise ValueError("no_activity")
        current.setdefault("participants", {}).pop(str(user_id), None)
        return len(current["participants"])

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def append_chain(group_id: str, user_id: str, nickname: str, content: str) -> int:
    value = clean_summary(content, 120)
    if not value:
        raise ValueError("missing_content")

    def mutator(data: dict) -> int:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict) or current.get("status") != "active":
            raise ValueError("no_activity")
        current.setdefault("chain", []).append(
            {"user_id": str(user_id), "nickname": clean_summary(nickname, 40), "content": value}
        )
        return len(current["chain"])

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def group_activity(group_id: str, group_count: int) -> list[list[tuple[str, str]]]:
    if group_count < 1:
        raise ValueError("invalid_group_count")

    def mutator(data: dict) -> list[list[tuple[str, str]]]:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict):
            raise ValueError("no_activity")
        participants = sorted(current.setdefault("participants", {}).items())
        if not participants:
            raise ValueError("no_participants")
        count = min(group_count, len(participants))
        seed = current.get("seed") or hashlib.sha256(
            f"{group_id}:{current['id']}:{','.join(key for key, _ in participants)}".encode()
        ).hexdigest()[:16]
        shuffled = list(participants)
        random.Random(seed).shuffle(shuffled)
        groups = [shuffled[index::count] for index in range(count)]
        current["seed"] = seed
        current["groups"] = groups
        return groups

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def set_activity_deadline(group_id: str, seconds: int) -> str:
    if seconds < 1 or seconds > 7 * 24 * 3600:
        raise ValueError("invalid_duration")
    deadline = datetime.now() + timedelta(seconds=seconds)

    def mutator(data: dict) -> None:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict):
            raise ValueError("no_activity")
        current["deadline"] = now_text(deadline)

    mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)
    return now_text(deadline)


def finish_activity(group_id: str, status: str) -> dict:
    if status not in {"finished", "cancelled"}:
        raise ValueError("invalid_status")

    def mutator(data: dict) -> dict:
        current = data.setdefault("groups", {}).setdefault(str(group_id), {}).get("current")
        if not isinstance(current, dict):
            raise ValueError("no_activity")
        current["status"] = status
        current["finished_at"] = now_text()
        return dict(current)

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)


def archive_activity(group_id: str) -> dict:
    activity = get_activity(group_id)
    if not activity or activity.get("status") == "active":
        raise ValueError("activity_not_finished")

    def add_archive(data: dict) -> None:
        items = data.setdefault("groups", {}).setdefault(str(group_id), [])
        if not any(str(item.get("id")) == str(activity["id"]) for item in items if isinstance(item, dict)):
            items.append(activity)
        del items[:-30]

    mutate_json(ACTIVITY_ARCHIVE_FILE, DEFAULT_GROUPS, add_archive)
    mutate_json(
        ACTIVITY_FILE,
        DEFAULT_GROUPS,
        lambda data: data.setdefault("groups", {}).setdefault(str(group_id), {}).pop("current", None),
    )
    return activity


def list_activity_archives(group_id: str) -> list[dict]:
    items = load_json(ACTIVITY_ARCHIVE_FILE, DEFAULT_GROUPS).get("groups", {}).get(str(group_id), [])
    return [dict(item) for item in items if isinstance(item, dict)][-10:]


def clear_activity_archives(group_id: str) -> int:
    def mutator(data: dict) -> int:
        groups = data.setdefault("groups", {})
        old = groups.pop(str(group_id), [])
        return len(old) if isinstance(old, list) else 0

    return mutate_json(ACTIVITY_ARCHIVE_FILE, DEFAULT_GROUPS, mutator)


def _activity_is_due(activity: object, current_time: datetime) -> bool:
    if not isinstance(activity, dict) or activity.get("status") != "active":
        return False
    deadline = str(activity.get("deadline", ""))
    if not deadline:
        return False
    try:
        return datetime.fromisoformat(deadline) <= current_time
    except ValueError:
        return False


def expire_due_activities(
    now: datetime | None = None,
    group_filter: Callable[[str], bool] | None = None,
) -> list[tuple[str, dict]]:
    current_time = now or datetime.now()
    snapshot = load_json(ACTIVITY_FILE, DEFAULT_GROUPS)
    candidates = {
        str(group_id): str(activity.get("id", ""))
        for group_id, group in snapshot.get("groups", {}).items()
        if (activity := group.get("current") if isinstance(group, dict) else None)
        and _activity_is_due(activity, current_time)
        and (group_filter is None or group_filter(str(group_id)))
    }
    if not candidates:
        return []

    def mutator(data: dict) -> list[tuple[str, dict]]:
        expired = []
        for group_id, expected_activity_id in candidates.items():
            group = data.setdefault("groups", {}).get(group_id)
            activity = group.get("current") if isinstance(group, dict) else None
            if (
                isinstance(activity, dict)
                and str(activity.get("id", "")) == expected_activity_id
                and _activity_is_due(activity, current_time)
            ):
                activity["status"] = "finished"
                activity["finished_at"] = now_text(current_time)
                expired.append((str(group_id), dict(activity)))
        return expired

    return mutate_json(ACTIVITY_FILE, DEFAULT_GROUPS, mutator)
