from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from mybot.common.json_store import load_json, mutate_json


ADMIN_AUDIT_FILE = Path(__file__).resolve().parent.parent / "data" / "admin_audit.json"
ADMIN_AUDIT_SCHEMA_VERSION = 1
MAX_RETAINED_AUDIT_RECORDS = 10_000
DEFAULT_ADMIN_AUDIT = {
    "schema_version": ADMIN_AUDIT_SCHEMA_VERSION,
    "records": [],
    "dropped_records": 0,
}

ALLOWED_DETAIL_KEYS = {
    "after",
    "amount",
    "before",
    "cleared_group_overrides",
    "command",
    "feature_key",
    "permission_level",
    "previous_permission_level",
}


def _normalize_id(value: str | int | None, field: str, *, required: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"{field}_required")
        return None
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise ValueError(f"invalid_{field}")
    return str(int(normalized))


def _normalize_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > 80:
        raise ValueError(f"invalid_{field}")
    return normalized


def _normalize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key not in ALLOWED_DETAIL_KEYS:
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            normalized[key] = value
        elif isinstance(value, str):
            normalized[key] = value[:120]
    return normalized


def record_admin_action(
    *,
    actor_user_id: str | int,
    action: str,
    scope: str,
    source_group_id: str | int | None = None,
    target_group_id: str | int | None = None,
    target_user_id: str | int | None = None,
    details: Mapping[str, Any] | None = None,
    store_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    actor = _normalize_id(actor_user_id, "actor_user_id", required=True)
    source_group = _normalize_id(source_group_id, "source_group_id")
    target_group = _normalize_id(target_group_id, "target_group_id")
    target_user = _normalize_id(target_user_id, "target_user_id")
    path = Path(store_path) if store_path is not None else ADMIN_AUDIT_FILE
    current = (now or datetime.now().astimezone()).astimezone()
    record = {
        "event_id": uuid4().hex,
        "timestamp": current.isoformat(timespec="seconds"),
        "actor_user_id": actor,
        "action": _normalize_text(action, "action"),
        "scope": _normalize_text(scope, "scope"),
        "source_group_id": source_group,
        "target_group_id": target_group,
        "target_user_id": target_user,
        "cross_group": bool(target_group and target_group != source_group),
        "details": _normalize_details(details),
    }

    def mutator(data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("invalid_admin_audit_data")
        version = data.get("schema_version", ADMIN_AUDIT_SCHEMA_VERSION)
        if isinstance(version, bool) or version != ADMIN_AUDIT_SCHEMA_VERSION:
            raise ValueError("unsupported_admin_audit_schema")
        records = data.setdefault("records", [])
        if not isinstance(records, list):
            raise ValueError("invalid_admin_audit_records")
        data["schema_version"] = ADMIN_AUDIT_SCHEMA_VERSION
        records.append(copy.deepcopy(record))
        overflow = max(0, len(records) - MAX_RETAINED_AUDIT_RECORDS)
        if overflow:
            del records[:overflow]
            try:
                dropped = int(data.get("dropped_records", 0))
            except (TypeError, ValueError):
                dropped = 0
            data["dropped_records"] = max(0, dropped) + overflow
        else:
            data.setdefault("dropped_records", 0)
        return copy.deepcopy(record)

    return mutate_json(path, DEFAULT_ADMIN_AUDIT, mutator)


def get_admin_audit_records(
    *,
    limit: int = 50,
    store_path: Path | str | None = None,
) -> list[dict]:
    path = Path(store_path) if store_path is not None else ADMIN_AUDIT_FILE
    data = load_json(path, DEFAULT_ADMIN_AUDIT)
    records = data.get("records", []) if isinstance(data, dict) else []
    if not isinstance(records, list):
        return []
    bounded = max(0, min(int(limit), 500))
    if bounded == 0:
        return []
    return [copy.deepcopy(item) for item in records[-bounded:] if isinstance(item, dict)]
