"""Read-only summaries for public, user-attributed group contributions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mybot.common.image_library import IMAGE_LIBRARY_ROOT, list_images
from mybot.common.json_store import load_json
from mybot.common.poetry_society import DATA_FILE as POETRY_SOCIETY_FILE


BOT_ROOT = Path(__file__).resolve().parent.parent
CLASSICS_FILE = BOT_ROOT / "data" / "classics.json"


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _quote_counts(data: Any, user_id: str, group_id: str) -> tuple[int, int]:
    group = _mapping(_mapping(_mapping(data).get("groups")).get(group_id))
    classics = _mapping(group.get("classics"))
    speaker_count = 0
    recorder_count = 0
    for owner_id, raw_records in classics.items():
        if not isinstance(raw_records, list):
            continue
        for raw_record in raw_records:
            if not isinstance(raw_record, dict):
                continue
            speaker_id = str(raw_record.get("speaker_id") or owner_id)
            if speaker_id == user_id:
                speaker_count += 1
            if str(raw_record.get("recorder_id") or "") == user_id:
                recorder_count += 1
    return speaker_count, recorder_count


def _poetry_submission_count(data: Any, user_id: str, group_id: str) -> int:
    group = _mapping(_mapping(_mapping(data).get("groups")).get(group_id))
    weeks = _mapping(group.get("weeks"))
    total = 0
    for raw_week in weeks.values():
        submissions = _mapping(_mapping(raw_week).get("submissions"))
        for raw_submission in submissions.values():
            submission = _mapping(raw_submission)
            if (
                str(submission.get("author_id") or "") == user_id
                and submission.get("status", "active") == "active"
            ):
                total += 1
    return total


def get_public_contribution_stats(
    user_id: str,
    group_id: str,
    *,
    classics_file: Path | str = CLASSICS_FILE,
    poetry_file: Path | str = POETRY_SOCIETY_FILE,
    image_root: Path = IMAGE_LIBRARY_ROOT,
) -> dict[str, int]:
    """Return public contribution counts without changing any runtime store."""

    user_key = str(user_id).strip()
    group_key = str(group_id).strip()
    quote_speaker_count, quote_recorder_count = _quote_counts(
        load_json(classics_file, {"groups": {}}),
        user_key,
        group_key,
    )
    poetry_submission_count = _poetry_submission_count(
        load_json(poetry_file, {"schema_version": 1, "groups": {}}),
        user_key,
        group_key,
    )
    image_saved_count = sum(
        1
        for record in list_images(group_key, root=image_root)
        if str(record.get("saved_by") or "") == user_key
    )
    total = (
        quote_speaker_count
        + quote_recorder_count
        + poetry_submission_count
        + image_saved_count
    )
    return {
        "quote_speaker_count": quote_speaker_count,
        "quote_recorder_count": quote_recorder_count,
        "poetry_submission_count": poetry_submission_count,
        "image_saved_count": image_saved_count,
        "total": total,
    }
