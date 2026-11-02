from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

CHAT_LOG_ROOT = Path(__file__).resolve().parent.parent / "data" / "group_chat_logs"
_WRITE_LOCK = RLock()
BOT_DISPLAY_NAME = "李太白给"
_SEGMENT_PLACEHOLDERS = {
    "image": "图片",
    "video": "视频",
    "record": "语音",
    "file": "文件",
    "at": "提及",
    "reply": "回复",
    "json": "卡片",
    "xml": "卡片",
    "forward": "合并转发",
    "node": "转发节点",
    "location": "位置",
    "music": "音乐",
    "share": "分享",
}


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


def _nested_value(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is not None:
        return value
    raw = data.get("raw")
    return raw.get(key) if isinstance(raw, dict) else None


def _slim_segment(segment_type: Any, data: Any) -> dict[str, Any]:
    kind = str(segment_type or "unknown")
    segment_data = data if isinstance(data, dict) else {}
    if kind == "text":
        return {
            "type": "text",
            "data": {"text": _clean_sender_value(segment_data.get("text"))},
        }
    if kind == "face":
        face_index = _nested_value(segment_data, "faceIndex")
        if face_index is None:
            face_index = segment_data.get("id")
        face_text = _nested_value(segment_data, "faceText")
        return {
            "type": "face",
            "data": {
                "faceIndex": face_index,
                "faceText": _clean_sender_value(face_text),
            },
        }
    return {
        "type": kind,
        "data": {"text": _SEGMENT_PLACEHOLDERS.get(kind, f"[{kind}]")},
    }


def slim_message_content(segments: Any, fallback_text: Any = "") -> list[dict[str, Any]]:
    """Return stable message content without transient OneBot metadata."""
    content: list[dict[str, Any]] = []
    if segments is not None:
        if isinstance(segments, str):
            message_segments = ({"type": "text", "data": {"text": segments}},)
        elif isinstance(segments, dict) or hasattr(segments, "type"):
            message_segments = (segments,)
        else:
            try:
                message_segments = iter(segments)
            except TypeError:
                message_segments = (segments,)
        for segment in message_segments:
            if isinstance(segment, dict):
                content.append(_slim_segment(segment.get("type"), segment.get("data")))
            else:
                content.append(
                    _slim_segment(
                        getattr(segment, "type", None),
                        getattr(segment, "data", None),
                    )
                )
    if not content and fallback_text:
        content.append(_slim_segment("text", {"text": fallback_text}))
    return content


def normalize_group_message_record(record: Any) -> dict[str, Any]:
    """Expose old and new log records through the current four-field shape."""
    source = record if isinstance(record, dict) else {}
    sender = source.get("sender")
    sender_data = sender if isinstance(sender, dict) else {}
    nickname = source.get("nickname")
    if nickname is None:
        nickname = sender_data.get("card") or sender_data.get("nickname") or ""
    content = source.get("content")
    if not isinstance(content, list):
        content = slim_message_content(source.get("segments"), source.get("text", ""))
    else:
        content = slim_message_content(content)
    return {
        "time": _clean_sender_value(source.get("time")),
        "user_id": _clean_sender_value(source.get("user_id")),
        "nickname": _clean_sender_value(nickname),
        "content": content,
    }


def build_group_message_record(
    event: GroupMessageEvent,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    now = captured_at or datetime.now()
    sender = event.sender
    return {
        "time": now.isoformat(timespec="seconds"),
        "user_id": str(event.user_id),
        "nickname": _clean_sender_value(
            getattr(sender, "card", "") or getattr(sender, "nickname", "")
        ),
        "content": slim_message_content(event.message),
    }


def build_sent_group_message_record(
    self_id: str | int,
    message: Any,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    now = captured_at or datetime.now()
    return {
        "time": now.isoformat(timespec="seconds"),
        "user_id": str(self_id),
        "nickname": BOT_DISPLAY_NAME,
        "content": slim_message_content(message),
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


def save_sent_group_message_record(
    group_id: str | int,
    self_id: str | int,
    message: Any,
    captured_at: datetime | None = None,
    root: Path = CHAT_LOG_ROOT,
) -> Path:
    now = captured_at or datetime.now()
    record = build_sent_group_message_record(self_id, message, now)
    path = get_group_log_path(group_id, now, root)
    _append_yaml_record(path, record)
    return path


def extract_sent_group_message(
    api: str,
    data: dict[str, Any],
) -> tuple[str | int, Any] | None:
    """Return group and message for OneBot APIs that send a normal group message."""
    if "message" not in data:
        return None
    group_id = data.get("group_id")
    if group_id is None:
        return None
    if api == "send_group_msg":
        return group_id, data["message"]
    if api != "send_msg":
        return None
    message_type = str(data.get("message_type") or "").lower()
    if message_type and message_type != "group":
        return None
    return group_id, data["message"]
