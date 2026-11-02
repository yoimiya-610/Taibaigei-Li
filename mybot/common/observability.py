from __future__ import annotations

import secrets
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from nonebot.adapters import Event
from nonebot.consts import CMD_KEY, PREFIX_KEY
from nonebot.matcher import Matcher
from nonebot.message import run_postprocessor, run_preprocessor
from nonebot.typing import T_State

from mybot.common.command_registry import collect_command_aliases
from mybot.common.logger import OBSERVABILITY_STATE_KEY, get_plugin_logger


logger = get_plugin_logger(__name__)
_hooks_installed = False


def new_business_id(*, now: datetime | None = None, entropy: str | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    suffix = (entropy or secrets.token_hex(4)).lower()
    return f"TB-{current:%Y%m%d%H%M%S}-{suffix}"


def _command_from_state(state: dict[Any, Any]) -> str | None:
    prefix = state.get(PREFIX_KEY)
    if not isinstance(prefix, dict):
        return None
    command = prefix.get(CMD_KEY)
    if isinstance(command, tuple) and command and all(isinstance(item, str) for item in command):
        return "/" + " ".join(command)
    return None


def _plain_command_from_event(event: Any) -> str | None:
    try:
        if event.get_type() != "message":
            return None
        text = event.get_plaintext().strip()
    except Exception:
        return None
    if not text or text.startswith(("/", "／")):
        return None
    for alias in sorted(collect_command_aliases(), key=len, reverse=True):
        if text == alias or (text.startswith(alias) and text[len(alias) : len(alias) + 1].isspace()):
            return alias
    return None


def _handler_name(matcher: Any) -> str:
    module_name = str(getattr(matcher, "module_name", "") or "unknown")
    return module_name.removeprefix("mybot.plugins.").removeprefix("mybot.")


async def _observe_run_start(matcher: Matcher, event: Event, state: T_State) -> None:
    command = _command_from_state(state) or _plain_command_from_event(event)
    observation = {
        "business_id": new_business_id(),
        "command": command or "-",
        "handler": _handler_name(matcher),
        "started_at": perf_counter(),
        "is_command": command is not None,
    }
    matcher.state[OBSERVABILITY_STATE_KEY] = observation
    if command is not None:
        logger.info("command_started handler=%s", observation["handler"])


async def _observe_run_finish(matcher: Matcher, exception: Exception | None = None) -> None:
    observation = matcher.state.get(OBSERVABILITY_STATE_KEY)
    if not isinstance(observation, dict) or not observation.get("is_command"):
        return
    started_at = observation.get("started_at")
    duration_ms = max(0.0, (perf_counter() - float(started_at)) * 1000) if started_at is not None else 0.0
    status = "error" if exception is not None else "ok"
    log_method = logger.error if exception is not None else logger.info
    log_method(
        "command_completed status=%s duration_ms=%.2f handler=%s exception=%s",
        status,
        duration_ms,
        observation.get("handler", "unknown"),
        exception.__class__.__name__ if exception is not None else "-",
    )


def install_observability_hooks() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    run_preprocessor(_observe_run_start)
    run_postprocessor(_observe_run_finish)
    _hooks_installed = True
