from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta
import hashlib
from pathlib import Path
import unicodedata
from zoneinfo import ZoneInfo

from mybot.common.json_store import load_json, mutate_json


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "poetry_society.json"
SCHEMA_VERSION = 1
MAX_VISIBLE_CHARACTERS = 200
HISTORY_LIMIT = 5
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_DATA = {"schema_version": SCHEMA_VERSION, "groups": {}}

THEMES = (
    "春夜微雨",
    "月下独酌",
    "长安旧梦",
    "江湖远行",
    "故园灯火",
    "山中清风",
    "夏夜听蝉",
    "秋窗落叶",
    "冬雪围炉",
    "渡口归舟",
    "城南花信",
    "云外雁书",
    "竹影茶烟",
    "星河入梦",
    "人间烟火",
    "相逢与别离",
    "少年意气",
    "岁月留痕",
    "酒醒黄昏",
    "雨后青山",
    "海上明月",
    "古道斜阳",
    "小楼听风",
    "一纸家书",
)


class PoetrySocietyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _normalize_id(value: str | int, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise PoetrySocietyError(f"invalid_{field_name}")
    return str(int(normalized))


def normalize_submission_id(value: str | int) -> str:
    normalized = str(value).strip().removeprefix("#").strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise PoetrySocietyError("invalid_submission_id")
    return str(int(normalized))


def format_submission_id(value: str | int) -> str:
    return f"#{int(normalize_submission_id(value)):04d}"


def _coerce_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI_TZ)
    return current.astimezone(SHANGHAI_TZ)


def week_key(year: int, week: int) -> str:
    date.fromisocalendar(int(year), int(week), 1)
    return f"{int(year):04d}-W{int(week):02d}"


def parse_week_key(value: str) -> tuple[int, int]:
    try:
        year_text, week_text = str(value).split("-W", 1)
        year, week = int(year_text), int(week_text)
        date.fromisocalendar(year, week, 1)
    except (TypeError, ValueError) as exc:
        raise PoetrySocietyError("invalid_week_key") from exc
    return year, week


def week_context(now: datetime | None = None) -> dict:
    current = _coerce_now(now)
    iso = current.isocalendar()
    return context_for_week(iso.year, iso.week, now=current)


def context_for_week(year: int, week: int, *, now: datetime | None = None) -> dict:
    monday = date.fromisocalendar(int(year), int(week), 1)
    start_at = datetime.combine(monday, time.min, SHANGHAI_TZ)
    cutoff_at = datetime.combine(monday + timedelta(days=6), time(21, 0), SHANGHAI_TZ)
    next_start_at = start_at + timedelta(days=7)
    current = _coerce_now(now)
    return {
        "key": week_key(year, week),
        "year": int(year),
        "week": int(week),
        "start_at": start_at,
        "cutoff_at": cutoff_at,
        "next_start_at": next_start_at,
        "phase": "open" if current < cutoff_at else "settled",
    }


def stable_theme(group_id: str | int, year: int, week: int) -> str:
    group_key = _normalize_id(group_id, "group_id")
    token = f"poetry-society-v1:{group_key}:{int(year):04d}:{int(week):02d}"
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return THEMES[int.from_bytes(digest[:8], "big") % len(THEMES)]


def visible_character_count(text: str) -> int:
    return sum(
        1
        for char in text
        if not char.isspace()
        and not unicodedata.category(char).startswith(("C", "M"))
    )


def clean_submission_text(text: str) -> str:
    if not isinstance(text, str):
        raise PoetrySocietyError("text_only")
    normalized = unicodedata.normalize("NFC", text)
    without_controls = "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    cleaned = " ".join(without_controls.split())
    visible_count = visible_character_count(cleaned)
    if visible_count == 0:
        raise PoetrySocietyError("empty_content")
    if visible_count > MAX_VISIBLE_CHARACTERS:
        raise PoetrySocietyError("content_too_long")
    return cleaned


def _clean_author_name(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    cleaned = "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in unicodedata.normalize("NFC", str(value))
    )
    return " ".join(cleaned.split())[:64] or fallback


def _normalize_root(data) -> dict:
    if not isinstance(data, dict):
        raise PoetrySocietyError("invalid_store")
    version = data.get("schema_version", SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise PoetrySocietyError("invalid_schema_version")
    if version > SCHEMA_VERSION:
        raise PoetrySocietyError("unsupported_schema_version")
    data["schema_version"] = SCHEMA_VERSION
    groups = data.setdefault("groups", {})
    if not isinstance(groups, dict):
        raise PoetrySocietyError("invalid_store")
    return data


def _derive_next_submission_id(weeks: dict) -> int:
    largest = 0
    for week in weeks.values():
        if not isinstance(week, dict):
            continue
        submissions = week.get("submissions", {})
        if not isinstance(submissions, dict):
            continue
        for value in submissions:
            try:
                largest = max(largest, int(value))
            except (TypeError, ValueError):
                continue
    return largest + 1


def _normalize_group(groups: dict, group_id: str) -> dict:
    group = groups.setdefault(
        group_id,
        {"next_submission_id": 1, "weeks": {}, "history": []},
    )
    if not isinstance(group, dict):
        raise PoetrySocietyError("invalid_group_store")
    weeks = group.setdefault("weeks", {})
    history = group.setdefault("history", [])
    if not isinstance(weeks, dict) or not isinstance(history, list):
        raise PoetrySocietyError("invalid_group_store")
    next_id = group.get("next_submission_id")
    if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id <= 0:
        group["next_submission_id"] = _derive_next_submission_id(weeks)
    group["history"] = list(dict.fromkeys(str(item) for item in history))
    return group


def _normalize_week_record(record: dict) -> dict:
    if not isinstance(record, dict):
        raise PoetrySocietyError("invalid_week_store")
    submissions = record.setdefault("submissions", {})
    votes = record.setdefault("votes", {})
    if not isinstance(submissions, dict) or not isinstance(votes, dict):
        raise PoetrySocietyError("invalid_week_store")
    return record


def _ensure_week(group_id: str, group: dict, year: int, week: int) -> dict:
    key = week_key(year, week)
    context = context_for_week(year, week)
    record = group["weeks"].setdefault(
        key,
        {
            "year": year,
            "week": week,
            "theme": stable_theme(group_id, year, week),
            "start_at": context["start_at"].isoformat(),
            "cutoff_at": context["cutoff_at"].isoformat(),
            "submissions": {},
            "votes": {},
        },
    )
    _normalize_week_record(record)
    record.setdefault("year", year)
    record.setdefault("week", week)
    record.setdefault("theme", stable_theme(group_id, year, week))
    record.setdefault("start_at", context["start_at"].isoformat())
    record.setdefault("cutoff_at", context["cutoff_at"].isoformat())
    return record


def _week_ordinal(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)


def _ensure_weeks_through(group_id: str, group: dict, current: dict) -> None:
    valid_keys = []
    for key in group["weeks"]:
        try:
            valid_keys.append((key, *parse_week_key(key)))
        except PoetrySocietyError:
            continue
    current_date = _week_ordinal(current["year"], current["week"])
    prior = [item for item in valid_keys if _week_ordinal(item[1], item[2]) <= current_date]
    if prior:
        _, year, week = max(prior, key=lambda item: _week_ordinal(item[1], item[2]))
        cursor = _week_ordinal(year, week)
    else:
        cursor = current_date
    while cursor <= current_date:
        iso = cursor.isocalendar()
        _ensure_week(group_id, group, iso.year, iso.week)
        cursor += timedelta(days=7)


def _submission_sort_key(submission: dict) -> tuple:
    submitted_at = str(submission.get("submitted_at") or "9999")
    try:
        numeric_id = int(submission.get("id"))
    except (TypeError, ValueError):
        numeric_id = 10**18
    return submitted_at, numeric_id


def _settle_week(group: dict, record: dict, key: str, settled_at: datetime) -> bool:
    if isinstance(record.get("settlement"), dict):
        return False

    active = [
        submission
        for submission in record["submissions"].values()
        if isinstance(submission, dict) and submission.get("status", "active") == "active"
    ]
    active_ids = {str(submission.get("id")) for submission in active}
    vote_counts = {submission_id: 0 for submission_id in active_ids}
    valid_votes = 0
    for vote in record["votes"].values():
        if not isinstance(vote, dict):
            continue
        submission_id = str(vote.get("submission_id") or "")
        if submission_id in vote_counts:
            vote_counts[submission_id] += 1
            valid_votes += 1

    ranked = sorted(
        active,
        key=lambda item: (
            -vote_counts.get(str(item.get("id")), 0),
            *_submission_sort_key(item),
        ),
    )
    rankings = []
    for rank, submission in enumerate(ranked, start=1):
        snapshot = copy.deepcopy(submission)
        snapshot["rank"] = rank
        snapshot["votes"] = vote_counts.get(str(submission.get("id")), 0)
        rankings.append(snapshot)

    if not rankings:
        outcome = "no_submissions"
    elif valid_votes == 0:
        outcome = "no_votes"
    else:
        outcome = "ranked"

    record["settlement"] = {
        "week_key": key,
        "year": int(record.get("year")),
        "week": int(record.get("week")),
        "theme": str(record.get("theme") or ""),
        "cutoff_at": str(record.get("cutoff_at") or ""),
        "settled_at": settled_at.isoformat(),
        "outcome": outcome,
        "total_submissions": len(rankings),
        "total_votes": valid_votes,
        "rankings": rankings,
        "notification": {
            "status": "pending",
            "updated_at": settled_at.isoformat(),
        },
    }
    if key not in group["history"]:
        group["history"].append(key)
    return True


def _recover_group_due(group_id: str, group: dict, current: datetime) -> list[dict]:
    context = week_context(current)
    _ensure_weeks_through(group_id, group, context)
    settled = []
    sortable = []
    for key, record in group["weeks"].items():
        try:
            year, week = parse_week_key(key)
        except PoetrySocietyError:
            continue
        sortable.append((_week_ordinal(year, week), key, record))
    for _, key, _record in sorted(sortable):
        year, week = parse_week_key(key)
        record = _ensure_week(group_id, group, year, week)
        cutoff = context_for_week(year, week)["cutoff_at"]
        if cutoff <= current and _settle_week(group, record, key, current):
            settled.append({"group_id": group_id, "week_key": key})
    return settled


def _current_week(group_id: str, group: dict, current: datetime) -> tuple[dict, dict]:
    context = week_context(current)
    record = _ensure_week(group_id, group, context["year"], context["week"])
    return context, record


def _phase(record: dict, context: dict) -> str:
    if isinstance(record.get("settlement"), dict) or context["phase"] == "settled":
        return "settled"
    return "open"


def _public_week_snapshot(record: dict, context: dict) -> dict:
    active_count = sum(
        1
        for submission in record["submissions"].values()
        if isinstance(submission, dict) and submission.get("status", "active") == "active"
    )
    return {
        "key": context["key"],
        "year": context["year"],
        "week": context["week"],
        "theme": str(record.get("theme") or ""),
        "start_at": context["start_at"].isoformat(),
        "cutoff_at": context["cutoff_at"].isoformat(),
        "next_start_at": context["next_start_at"].isoformat(),
        "phase": _phase(record, context),
        "active_submissions": active_count,
        "settlement": copy.deepcopy(record.get("settlement")),
    }


def _mutate_group(group_id: str | int, now: datetime | None, operation):
    group_key = _normalize_id(group_id, "group_id")
    current = _coerce_now(now)

    def mutator(data: dict):
        root = _normalize_root(data)
        group = _normalize_group(root["groups"], group_key)
        newly_settled = _recover_group_due(group_key, group, current)
        context, record = _current_week(group_key, group, current)
        try:
            result = operation(group, record, context, current)
        except PoetrySocietyError as exc:
            return {"operation_error": exc.code, "newly_settled": newly_settled}
        result["newly_settled"] = newly_settled
        return result

    result = mutate_json(DATA_FILE, DEFAULT_DATA, mutator)
    if result.get("operation_error"):
        raise PoetrySocietyError(result["operation_error"])
    return result


def get_overview(group_id: str | int, now: datetime | None = None) -> dict:
    return _mutate_group(
        group_id,
        now,
        lambda _group, record, context, _current: {
            "week": _public_week_snapshot(record, context)
        },
    )


def get_overview_snapshot(group_id: str | int, now: datetime | None = None) -> dict:
    """Return the current public week without creating or settling stored state."""

    group_key = _normalize_id(group_id, "group_id")
    current = _coerce_now(now)
    root = _normalize_root(load_json(DATA_FILE, DEFAULT_DATA))
    group = _normalize_group(root["groups"], group_key)
    context, record = _current_week(group_key, group, current)
    return {"week": _public_week_snapshot(record, context)}


def submit_work(
    group_id: str | int,
    user_id: str | int,
    content: str,
    *,
    author_name: str | None = None,
    now: datetime | None = None,
) -> dict:
    user_key = _normalize_id(user_id, "user_id")
    cleaned = clean_submission_text(content)

    def operation(group: dict, record: dict, context: dict, current: datetime) -> dict:
        if _phase(record, context) != "open":
            raise PoetrySocietyError("closed")
        if any(
            isinstance(item, dict)
            and item.get("status", "active") == "active"
            and str(item.get("author_id")) == user_key
            for item in record["submissions"].values()
        ):
            raise PoetrySocietyError("duplicate_submission")

        submission_id = str(group["next_submission_id"])
        group["next_submission_id"] += 1
        submission = {
            "id": submission_id,
            "author_id": user_key,
            "author_name": _clean_author_name(author_name, user_key),
            "content": cleaned,
            "submitted_at": current.isoformat(),
            "status": "active",
        }
        record["submissions"][submission_id] = submission
        return {"week": _public_week_snapshot(record, context), "submission": copy.deepcopy(submission)}

    return _mutate_group(group_id, now, operation)


def _find_current_submission(record: dict, submission_id: str) -> dict | None:
    submission = record["submissions"].get(submission_id)
    return submission if isinstance(submission, dict) else None


def _exists_in_other_week(group: dict, current_key: str, submission_id: str) -> bool:
    for key, week in group["weeks"].items():
        if key == current_key or not isinstance(week, dict):
            continue
        submissions = week.get("submissions", {})
        if isinstance(submissions, dict) and submission_id in submissions:
            return True
    return False


def _remove_votes_for(record: dict, submission_id: str) -> int:
    voters = [
        voter
        for voter, vote in record["votes"].items()
        if isinstance(vote, dict) and str(vote.get("submission_id")) == submission_id
    ]
    for voter in voters:
        record["votes"].pop(voter, None)
    return len(voters)


def withdraw_work(
    group_id: str | int,
    user_id: str | int,
    *,
    now: datetime | None = None,
) -> dict:
    user_key = _normalize_id(user_id, "user_id")

    def operation(_group: dict, record: dict, context: dict, current: datetime) -> dict:
        if _phase(record, context) != "open":
            raise PoetrySocietyError("closed")
        submission = next(
            (
                item
                for item in record["submissions"].values()
                if isinstance(item, dict)
                and item.get("status", "active") == "active"
                and str(item.get("author_id")) == user_key
            ),
            None,
        )
        if submission is None:
            raise PoetrySocietyError("no_submission")
        submission["status"] = "withdrawn"
        submission["withdrawn_at"] = current.isoformat()
        invalidated = _remove_votes_for(record, str(submission["id"]))
        return {
            "week": _public_week_snapshot(record, context),
            "submission": copy.deepcopy(submission),
            "invalidated_votes": invalidated,
        }

    return _mutate_group(group_id, now, operation)


def remove_work(
    group_id: str | int,
    submission_id: str | int,
    removed_by: str | int,
    *,
    now: datetime | None = None,
) -> dict:
    normalized_id = normalize_submission_id(submission_id)
    remover_key = _normalize_id(removed_by, "user_id")

    def operation(group: dict, record: dict, context: dict, current: datetime) -> dict:
        if _phase(record, context) != "open":
            raise PoetrySocietyError("closed")
        submission = _find_current_submission(record, normalized_id)
        if submission is None:
            if _exists_in_other_week(group, context["key"], normalized_id):
                raise PoetrySocietyError("old_submission")
            raise PoetrySocietyError("missing_submission")
        if submission.get("status", "active") != "active":
            raise PoetrySocietyError("inactive_submission")
        submission["status"] = "removed"
        submission["removed_at"] = current.isoformat()
        submission["removed_by"] = remover_key
        invalidated = _remove_votes_for(record, normalized_id)
        return {
            "week": _public_week_snapshot(record, context),
            "submission": copy.deepcopy(submission),
            "invalidated_votes": invalidated,
        }

    return _mutate_group(group_id, now, operation)


def cast_vote(
    group_id: str | int,
    voter_id: str | int,
    submission_id: str | int,
    *,
    now: datetime | None = None,
) -> dict:
    voter_key = _normalize_id(voter_id, "user_id")
    normalized_id = normalize_submission_id(submission_id)

    def operation(group: dict, record: dict, context: dict, current: datetime) -> dict:
        if _phase(record, context) != "open":
            raise PoetrySocietyError("closed")
        submission = _find_current_submission(record, normalized_id)
        if submission is None:
            if _exists_in_other_week(group, context["key"], normalized_id):
                raise PoetrySocietyError("old_submission")
            raise PoetrySocietyError("missing_submission")
        if submission.get("status", "active") != "active":
            raise PoetrySocietyError("inactive_submission")
        if str(submission.get("author_id")) == voter_key:
            raise PoetrySocietyError("self_vote")
        previous = record["votes"].get(voter_key)
        previous_id = (
            str(previous.get("submission_id"))
            if isinstance(previous, dict) and previous.get("submission_id") is not None
            else None
        )
        record["votes"][voter_key] = {
            "submission_id": normalized_id,
            "voted_at": current.isoformat(),
        }
        return {
            "week": _public_week_snapshot(record, context),
            "submission": copy.deepcopy(submission),
            "previous_submission_id": previous_id,
            "changed": previous_id is not None and previous_id != normalized_id,
        }

    return _mutate_group(group_id, now, operation)


def list_works(group_id: str | int, now: datetime | None = None) -> dict:
    def operation(_group: dict, record: dict, context: dict, _current: datetime) -> dict:
        settlement = record.get("settlement")
        if isinstance(settlement, dict):
            works = copy.deepcopy(settlement.get("rankings", []))
        else:
            works = sorted(
                (
                    copy.deepcopy(item)
                    for item in record["submissions"].values()
                    if isinstance(item, dict) and item.get("status", "active") == "active"
                ),
                key=_submission_sort_key,
            )
        return {"week": _public_week_snapshot(record, context), "works": works}

    return _mutate_group(group_id, now, operation)


def get_history(
    group_id: str | int,
    now: datetime | None = None,
    *,
    limit: int = HISTORY_LIMIT,
) -> dict:
    safe_limit = max(1, min(int(limit), 20))

    def operation(group: dict, record: dict, context: dict, _current: datetime) -> dict:
        rows = []
        sortable = []
        for key in group["history"]:
            try:
                year, week = parse_week_key(key)
            except PoetrySocietyError:
                continue
            week_record = group["weeks"].get(key)
            if not isinstance(week_record, dict) or not isinstance(week_record.get("settlement"), dict):
                continue
            sortable.append((_week_ordinal(year, week), week_record["settlement"]))
        for _, settlement in sorted(sortable, reverse=True)[:safe_limit]:
            rows.append(copy.deepcopy(settlement))
        return {
            "week": _public_week_snapshot(record, context),
            "history": rows,
        }

    return _mutate_group(group_id, now, operation)


def recover_all_due(now: datetime | None = None) -> list[dict]:
    current = _coerce_now(now)

    def mutator(data: dict) -> list[dict]:
        root = _normalize_root(data)
        recovered = []
        for group_id in sorted(root["groups"]):
            group = _normalize_group(root["groups"], str(group_id))
            recovered.extend(_recover_group_due(str(group_id), group, current))
        return recovered

    return mutate_json(DATA_FILE, DEFAULT_DATA, mutator)


def list_pending_notifications(group_id: str | int | None = None) -> list[dict]:
    group_key = _normalize_id(group_id, "group_id") if group_id is not None else None

    def mutator(data: dict) -> list[dict]:
        root = _normalize_root(data)
        pending = []
        for candidate, raw_group in root["groups"].items():
            if group_key is not None and str(candidate) != group_key:
                continue
            group = _normalize_group(root["groups"], str(candidate))
            for key, record in group["weeks"].items():
                if not isinstance(record, dict):
                    continue
                settlement = record.get("settlement")
                if not isinstance(settlement, dict):
                    continue
                notification = settlement.get("notification")
                if not isinstance(notification, dict):
                    notification = {"status": "pending"}
                    settlement["notification"] = notification
                if notification.get("status") == "pending":
                    pending.append({"group_id": str(candidate), "week_key": key})
        pending.sort(key=lambda item: (item["group_id"], item["week_key"]))
        return pending

    return mutate_json(DATA_FILE, DEFAULT_DATA, mutator)


def claim_notification(
    group_id: str | int,
    target_week: str,
    *,
    now: datetime | None = None,
) -> dict | None:
    group_key = _normalize_id(group_id, "group_id")
    parse_week_key(target_week)
    current = _coerce_now(now)

    def mutator(data: dict) -> dict | None:
        root = _normalize_root(data)
        raw_group = root["groups"].get(group_key)
        if not isinstance(raw_group, dict):
            return None
        group = _normalize_group(root["groups"], group_key)
        record = group["weeks"].get(target_week)
        if not isinstance(record, dict) or not isinstance(record.get("settlement"), dict):
            return None
        settlement = record["settlement"]
        notification = settlement.get("notification")
        if not isinstance(notification, dict):
            notification = {"status": "pending"}
            settlement["notification"] = notification
        if notification.get("status") != "pending":
            return None
        notification["status"] = "sending"
        notification["updated_at"] = current.isoformat()
        return copy.deepcopy(settlement)

    return mutate_json(DATA_FILE, DEFAULT_DATA, mutator)


def finish_notification(
    group_id: str | int,
    target_week: str,
    *,
    success: bool,
    now: datetime | None = None,
) -> bool:
    group_key = _normalize_id(group_id, "group_id")
    parse_week_key(target_week)
    current = _coerce_now(now)

    def mutator(data: dict) -> bool:
        root = _normalize_root(data)
        raw_group = root["groups"].get(group_key)
        if not isinstance(raw_group, dict):
            return False
        group = _normalize_group(root["groups"], group_key)
        record = group["weeks"].get(target_week)
        if not isinstance(record, dict) or not isinstance(record.get("settlement"), dict):
            return False
        notification = record["settlement"].get("notification")
        if not isinstance(notification, dict):
            notification = {"status": "pending"}
            record["settlement"]["notification"] = notification
        if notification.get("status") != "sending":
            return False
        notification["status"] = "sent" if success else "failed"
        notification["updated_at"] = current.isoformat()
        return True

    return mutate_json(DATA_FILE, DEFAULT_DATA, mutator)
