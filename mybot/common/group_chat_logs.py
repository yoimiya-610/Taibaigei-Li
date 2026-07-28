from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from mybot.common.message_utils import get_message_text


CHAT_LOG_ROOT = Path(__file__).resolve().parent.parent / "data" / "group_chat_logs"
_WRITE_LOCK = RLock()


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _dump_yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def _append_yaml_record(path: Path, record: dict[str, Any]) -> None:
    lines = _dump_yaml_lines([record])
    text = "\n".join(lines) + "\n"
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(text)


def _clean_sender_value(value: Any) -> str:
    return "" if value is None else str(value)


def build_group_message_record(
    event: GroupMessageEvent,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    now = captured_at or datetime.now()
    sender = event.sender
    return {
        "time": now.isoformat(timespec="seconds"),
        "message_id": getattr(event, "message_id", None),
        "group_id": str(event.group_id),
        "user_id": str(event.user_id),
        "sender": {
            "nickname": _clean_sender_value(getattr(sender, "nickname", "")),
            "card": _clean_sender_value(getattr(sender, "card", "")),
            "role": _clean_sender_value(getattr(sender, "role", "")),
        },
        "text": get_message_text(event),
        "segments": [
            {
                "type": segment.type,
                "data": dict(segment.data),
            }
            for segment in event.message
        ],
    }


def get_group_log_path(
    group_id: str | int,
    captured_at: datetime | None = None,
    root: Path = CHAT_LOG_ROOT,
) -> Path:
    now = captured_at or datetime.now()
    return root / str(group_id) / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}.yaml"


def save_group_message_record(
    event: GroupMessageEvent,
    captured_at: datetime | None = None,
    root: Path = CHAT_LOG_ROOT,
) -> Path:
    now = captured_at or datetime.now()
    record = build_group_message_record(event, now)
    path = get_group_log_path(event.group_id, now, root)
    _append_yaml_record(path, record)
    return path
