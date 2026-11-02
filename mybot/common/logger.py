from __future__ import annotations

import logging
import re
import threading
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from nonebot.matcher import current_event, current_matcher


LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

OBSERVABILITY_STATE_KEY = "_taibai_observability"
REDACTED = "<redacted>"

_SECRET_FIELD_RE = re.compile(
    r"(?i)(\b(?:[\w-]*api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|"
    r"token|secret|password|passwd|cookie)\b\s*[:=]\s*)([\"']?)([^\s,;\"']+)([\"']?)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_IDENTIFIER_FIELD_RE = re.compile(
    r"(?i)(\b(?:user_id|group_id|target_id|actor_user_id|source_group_id|"
    r"target_group_id|qq)\b\s*[:=]\s*)([\"']?)(\d{5,})([\"']?)"
)


def mask_identifier(value: Any) -> str:
    """Keep identifiers useful for correlation without writing the full value."""
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    if not text.isdigit():
        return REDACTED
    if len(text) <= 4:
        return "*" * len(text)
    visible = 2 if len(text) <= 8 else 3
    return f"{text[:visible]}{'*' * (len(text) - visible * 2)}{text[-visible:]}"


def redact_sensitive_text(value: Any, *, flatten_newlines: bool = True) -> str:
    """Redact credentials and personal identifiers from a rendered log value."""
    text = str(value)
    text = _BEARER_RE.sub(f"Bearer {REDACTED}", text)

    def redact_secret(match: re.Match[str]) -> str:
        quote = match.group(2) or match.group(4) or ""
        return f"{match.group(1)}{quote}{REDACTED}{quote}"

    text = _SECRET_FIELD_RE.sub(redact_secret, text)

    def redact_identifier(match: re.Match[str]) -> str:
        quote = match.group(2) or match.group(4) or ""
        return f"{match.group(1)}{quote}{mask_identifier(match.group(3))}{quote}"

    text = _IDENTIFIER_FIELD_RE.sub(redact_identifier, text)
    if flatten_newlines:
        text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text


def _safe_context_value(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    normalized = redact_sensitive_text(value)
    return normalized or fallback


def _current_log_context() -> dict[str, str]:
    context = {
        "business_id": "-",
        "event_type": "-",
        "command": "-",
        "group_id": "-",
        "user_id": "-",
    }
    try:
        event = current_event.get()
    except LookupError:
        event = None
    try:
        matcher = current_matcher.get()
    except LookupError:
        matcher = None

    if event is not None:
        try:
            context["event_type"] = _safe_context_value(event.get_type())
        except Exception:
            context["event_type"] = event.__class__.__name__
        context["group_id"] = mask_identifier(getattr(event, "group_id", None))
        try:
            context["user_id"] = mask_identifier(event.get_user_id())
        except Exception:
            pass

    observation = getattr(matcher, "state", {}).get(OBSERVABILITY_STATE_KEY, {}) if matcher else {}
    if isinstance(observation, dict):
        context["business_id"] = _safe_context_value(observation.get("business_id"))
        context["command"] = _safe_context_value(observation.get("command"))
    return context


class ObservabilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        record.msg = redact_sensitive_text(rendered)
        record.args = ()
        if record.stack_info:
            record.stack_info = redact_sensitive_text(record.stack_info, flatten_newlines=False)
        for key, value in _current_log_context().items():
            existing = getattr(record, key, None)
            if existing is None:
                setattr(record, key, value)
            elif key in {"group_id", "user_id"}:
                setattr(record, key, mask_identifier(existing))
            else:
                setattr(record, key, _safe_context_value(existing))
        return True


class RedactingFormatter(logging.Formatter):
    def formatException(self, ei) -> str:  # noqa: N802 - logging API name
        return redact_sensitive_text(super().formatException(ei), flatten_newlines=False)


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # Windows does not allow renaming a log file held by another process.
            if self.stream is None:
                self.stream = self._open()

            current_time = int(time.time())
            rollover_at = self.computeRollover(current_time)
            while rollover_at <= current_time:
                rollover_at += self.interval
            self.rolloverAt = rollover_at


_handler_lock = threading.Lock()
_shared_file_handler: SafeTimedRotatingFileHandler | None = None


def _get_shared_file_handler() -> SafeTimedRotatingFileHandler:
    global _shared_file_handler
    if _shared_file_handler is not None:
        return _shared_file_handler
    with _handler_lock:
        if _shared_file_handler is None:
            handler = SafeTimedRotatingFileHandler(
                LOG_DIR / "bot.log",
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
                delay=True,
            )
            handler.suffix = "%Y-%m-%d"
            handler.setLevel(logging.INFO)
            handler.addFilter(ObservabilityFilter())
            handler.setFormatter(
                RedactingFormatter(
                    "[%(asctime)s] [%(name)s] [%(levelname)s] "
                    "[business_id=%(business_id)s] "
                    "[event=%(event_type)s command=%(command)s "
                    "group_id=%(group_id)s user_id=%(user_id)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            _shared_file_handler = handler
    return _shared_file_handler


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _get_shared_file_handler()
    if handler not in logger.handlers:
        logger.addHandler(handler)
    return logger


def get_plugin_logger(module_name: str) -> logging.Logger:
    plugin_name = module_name.removeprefix("mybot.")
    plugin_name = plugin_name.removeprefix("plugins.").removeprefix("common.")
    return get_logger(f"plugin.{plugin_name}")


bot_logger = get_logger("bot")


def log_info(msg: str):
    bot_logger.info(msg)


def log_error(msg: str):
    bot_logger.error(msg)


def log_exception(msg: str):
    bot_logger.exception(msg)


def log_warning(msg: str):
    bot_logger.warning(msg)


def log_game(game: str, user: str, action: str, result: str = ""):
    """记录游戏日志"""
    bot_logger.info("[GAME:%s] user_id=%s action=%s result=%s", game, user, action, result)


def log_points(user: str, change: int, reason: str):
    """记录积分变动"""
    bot_logger.info("[POINTS] user_id=%s change=%+d reason=%s", user, change, reason)
