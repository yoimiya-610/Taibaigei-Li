from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from common.charm import get_monthly_charm_gains
from common.interaction_stats import get_monthly_auto_reply_counts
from common.json_store import load_json, mutate_json
from common.titles import grant_title


BOT_ROOT = Path(__file__).resolve().parent.parent
FORTUNE_FILE = BOT_ROOT / "data" / "fortune_data.json"
CLASSICS_FILE = BOT_ROOT / "data" / "classics.json"
FAME_FILE = BOT_ROOT / "data" / "monthly_fame.json"
DEFAULT_FAME_DATA = {"groups": {}}

RANK_TITLES = {
    1: "monthly_fame_first",
    2: "monthly_fame_second",
    3: "monthly_fame_third",
}


def previous_month(today: date | None = None) -> str:
    today = today or date.today()
    first_day = today.replace(day=1)
    last_month_day = first_day - timedelta(days=1)
    return last_month_day.strftime("%Y-%m")


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m")
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _score_bucket() -> dict[str, float]:
    return defaultdict(float)


def _add_score(scores: dict[str, float], user_id: str, amount: float) -> None:
    if user_id:
        scores[user_id] += amount


def _fortune_user_from_key(record_key: str, group_id: str) -> tuple[str, str] | None:
    parts = record_key.split("_")
    if len(parts) >= 3 and parts[-2] == group_id:
        return parts[0], parts[-1]
    return None


def _apply_fortune_scores(scores: dict[str, float], group_id: str, month: str) -> None:
    data = load_json(FORTUNE_FILE, {"fortune_record": {}, "makeup_records": {}})
    signed_dates: dict[str, set[str]] = defaultdict(set)

    fortune_records = data.get("fortune_record", {})
    if isinstance(fortune_records, dict):
        for record_key, record in fortune_records.items():
            parsed = _fortune_user_from_key(str(record_key), group_id)
            if not parsed or not isinstance(record, dict):
                continue
            day_text, user_id = parsed
            if not day_text.startswith(month):
                continue
            signed_dates[user_id].add(day_text)
            fortune = str(record.get("fortune", ""))
            if fortune == "？？？":
                _add_score(scores, user_id, 100)
            elif fortune == "天命之子":
                _add_score(scores, user_id, 36)
            elif fortune == "大凶":
                _add_score(scores, user_id, 20)
            elif fortune == "大吉":
                _add_score(scores, user_id, 12)

    makeup_records = data.get("makeup_records", {})
    if isinstance(makeup_records, dict):
        prefix = f"{group_id}_"
        for key, record in makeup_records.items():
            if not str(key).startswith(prefix) or not isinstance(record, dict):
                continue
            user_id = str(key)[len(prefix):]
            for day_text in record.get("dates", []):
                if isinstance(day_text, str) and day_text.startswith(month):
                    signed_dates[user_id].add(day_text)

    for user_id, dates in signed_dates.items():
        _add_score(scores, user_id, len(dates) * 9)


def _apply_charm_scores(scores: dict[str, float], group_id: str, month: str) -> None:
    for user_id, charm in get_monthly_charm_gains(group_id, month).items():
        _add_score(scores, user_id, charm * 1.2)


def _apply_auto_reply_scores(scores: dict[str, float], group_id: str, month: str) -> None:
    for user_id, count in get_monthly_auto_reply_counts(group_id, month).items():
        _add_score(scores, user_id, count * 10)


def _apply_quote_scores(scores: dict[str, float], group_id: str, month: str) -> None:
    start, end = _month_bounds(month)
    data = load_json(CLASSICS_FILE, {"groups": {}})
    group = data.get("groups", {}).get(group_id, {})
    classics = group.get("classics", {})
    if not isinstance(classics, dict):
        return

    for speaker_id, records in classics.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            timestamp = record.get("recorded_timestamp")
            if not timestamp:
                continue
            try:
                recorded_at = datetime.fromtimestamp(float(timestamp))
            except (TypeError, ValueError, OSError):
                continue
            if not (start <= recorded_at < end):
                continue
            _add_score(scores, str(speaker_id), 18)
            _add_score(scores, str(record.get("recorder_id") or ""), 9)


def calculate_monthly_fame(group_id: str, month: str) -> list[dict]:
    scores = _score_bucket()
    _apply_fortune_scores(scores, group_id, month)
    _apply_charm_scores(scores, group_id, month)
    _apply_auto_reply_scores(scores, group_id, month)
    _apply_quote_scores(scores, group_id, month)

    rows = [
        {"user_id": user_id, "score": round(score, 3)}
        for user_id, score in scores.items()
        if score > 0
    ]
    rows.sort(key=lambda row: (-row["score"], row["user_id"]))
    return rows[:3]


def _is_settled(data: dict, group_id: str, month: str) -> bool:
    return bool(data.get("groups", {}).get(group_id, {}).get(month, {}).get("settled"))


def settle_monthly_fame(group_id: str, month: str | None = None) -> dict:
    month = month or previous_month()
    data = load_json(FAME_FILE, DEFAULT_FAME_DATA)
    if _is_settled(data, group_id, month):
        return dict(data["groups"][group_id][month]) | {"already": True}

    rankings = calculate_monthly_fame(group_id, month)
    awards = []
    for index, row in enumerate(rankings, 1):
        title = grant_title(row["user_id"], group_id, RANK_TITLES[index])
        awards.append(
            {
                "rank": index,
                "user_id": row["user_id"],
                "title_id": title.id if title else "",
                "title": title.title if title else "",
            }
        )

    settled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mutator(current: dict) -> dict:
        group = current.setdefault("groups", {}).setdefault(group_id, {})
        record = {
            "month": month,
            "settled": True,
            "settled_at": settled_at,
            "rankings": rankings,
            "awards": awards,
        }
        group[month] = record
        return dict(record)

    record = mutate_json(FAME_FILE, DEFAULT_FAME_DATA, mutator)
    record["already"] = False
    return record
