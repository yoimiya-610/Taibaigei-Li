from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import re
from threading import RLock
from typing import Any, Mapping

from nonebot.adapters.onebot.v11 import Bot

from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)

PROBE_TIMEOUT_SECONDS = 3.0
READ_ONLY_PROBE_ACTIONS = ("get_version_info", "get_status")


class Capability(str, Enum):
    PROFILE_LIKE = "profile_like"
    GROUP_POKE = "group_poke"
    ESSENCE_MESSAGE = "essence_message"
    IMAGE_REFRESH = "image_refresh"
    IMAGE_OCR = "image_ocr"


class CapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    PROBING = "probing"
    CONNECTED = "connected"
    DEGRADED = "degraded"


class ImplementationFamily(str, Enum):
    NAPCAT = "napcat"
    ONEBOT = "onebot"
    UNKNOWN = "unknown"


CAPABILITY_LABELS: Mapping[Capability, str] = {
    Capability.PROFILE_LIKE: "名片点赞",
    Capability.GROUP_POKE: "群戳一戳",
    Capability.ESSENCE_MESSAGE: "精华消息",
    Capability.IMAGE_REFRESH: "图片地址刷新",
    Capability.IMAGE_OCR: "图片 OCR",
}

CAPABILITY_ACTIONS: Mapping[Capability, frozenset[str]] = {
    Capability.PROFILE_LIKE: frozenset({"send_like"}),
    Capability.GROUP_POKE: frozenset({"group_poke"}),
    Capability.ESSENCE_MESSAGE: frozenset(
        {"get_essence_msg_list", "set_essence_msg", "delete_essence_msg"}
    ),
    Capability.IMAGE_REFRESH: frozenset({"get_image"}),
    Capability.IMAGE_OCR: frozenset({"ocr_image", ".ocr_image"}),
}

MINIMUM_CAPABILITIES = frozenset(
    {Capability.PROFILE_LIKE, Capability.IMAGE_REFRESH}
)
OPTIONAL_CAPABILITIES = frozenset(set(Capability) - set(MINIMUM_CAPABILITIES))

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()\-]{0,63}$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+()\-]{0,31}$")
_SENSITIVE_NAME_MARKERS = ("access", "password", "secret", "token", "websocket")
_UNSUPPORTED_MARKERS = (
    "unsupported",
    "not support",
    "not implemented",
    "unknown action",
    "action not found",
    "api not found",
    "不支持",
    "未实现",
    "未知操作",
)


@dataclass(frozen=True)
class CapabilityRecord:
    capability: Capability
    status: CapabilityStatus
    basis: str


@dataclass(frozen=True)
class ImplementationInfo:
    name: str
    version: str
    protocol_version: str
    family: ImplementationFamily


@dataclass(frozen=True)
class OneBotCapabilitySnapshot:
    generation: int
    adapter_connected: bool
    adapter_name: str
    connection_status: ConnectionStatus
    implementation_name: str | None
    implementation_version: str | None
    protocol_version: str | None
    implementation_family: ImplementationFamily
    probe_issue: str | None
    capabilities: tuple[CapabilityRecord, ...]

    def capability(self, capability: Capability | str) -> CapabilityRecord:
        normalized = Capability(capability)
        for record in self.capabilities:
            if record.capability is normalized:
                return record
        raise KeyError(normalized)


class CapabilityUnavailable(RuntimeError):
    def __init__(
        self,
        capability: Capability,
        status: CapabilityStatus,
    ) -> None:
        super().__init__(f"{capability.value}:{status.value}")
        self.capability = capability
        self.status = status


def _capability_defaults(
    family: ImplementationFamily,
) -> dict[Capability, CapabilityRecord]:
    records: dict[Capability, CapabilityRecord] = {}
    for capability in Capability:
        if capability in MINIMUM_CAPABILITIES:
            records[capability] = CapabilityRecord(
                capability,
                CapabilityStatus.SUPPORTED,
                "onebot_v11_standard",
            )
        elif family is ImplementationFamily.NAPCAT:
            records[capability] = CapabilityRecord(
                capability,
                CapabilityStatus.SUPPORTED,
                "napcat_declaration",
            )
        elif family is ImplementationFamily.ONEBOT:
            records[capability] = CapabilityRecord(
                capability,
                CapabilityStatus.UNSUPPORTED,
                "outside_onebot_v11_standard",
            )
        else:
            records[capability] = CapabilityRecord(
                capability,
                CapabilityStatus.UNKNOWN,
                "unrecognized_implementation",
            )
    return records


class OneBotCapabilityRegistry:
    """In-memory OneBot connection and capability state.

    The registry deliberately stores no token, endpoint, account identifier, group
    identifier, or raw API response.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._generation = 0
        self._adapter_connected = False
        self._adapter_name = "OneBot V11"
        self._connection_status = ConnectionStatus.DISCONNECTED
        self._implementation_name: str | None = None
        self._implementation_version: str | None = None
        self._protocol_version: str | None = None
        self._implementation_family = ImplementationFamily.UNKNOWN
        self._probe_issue: str | None = None
        self._capabilities = {
            capability: CapabilityRecord(
                capability,
                CapabilityStatus.UNKNOWN,
                "not_connected",
            )
            for capability in Capability
        }

    def snapshot(self) -> OneBotCapabilitySnapshot:
        with self._lock:
            return OneBotCapabilitySnapshot(
                generation=self._generation,
                adapter_connected=self._adapter_connected,
                adapter_name=self._adapter_name,
                connection_status=self._connection_status,
                implementation_name=self._implementation_name,
                implementation_version=self._implementation_version,
                protocol_version=self._protocol_version,
                implementation_family=self._implementation_family,
                probe_issue=self._probe_issue,
                capabilities=tuple(
                    self._capabilities[capability] for capability in Capability
                ),
            )

    def begin_connection(self, adapter_name: str = "OneBot V11") -> int:
        with self._lock:
            self._generation += 1
            self._adapter_connected = True
            self._adapter_name = _safe_adapter_name(adapter_name)
            self._connection_status = ConnectionStatus.PROBING
            self._implementation_name = None
            self._implementation_version = None
            self._protocol_version = None
            self._implementation_family = ImplementationFamily.UNKNOWN
            self._probe_issue = None
            self._capabilities = _capability_defaults(ImplementationFamily.UNKNOWN)
            return self._generation

    def apply_probe(
        self,
        generation: int,
        implementation: ImplementationInfo | None,
        *,
        healthy: bool | None,
        issue: str | None,
    ) -> OneBotCapabilitySnapshot:
        with self._lock:
            if generation != self._generation or not self._adapter_connected:
                return self.snapshot()

            family = (
                implementation.family
                if implementation is not None
                else ImplementationFamily.UNKNOWN
            )
            self._implementation_family = family
            self._implementation_name = implementation.name if implementation else None
            self._implementation_version = (
                implementation.version if implementation else None
            )
            self._protocol_version = (
                implementation.protocol_version if implementation else None
            )
            self._probe_issue = issue or ("reported_unhealthy" if healthy is False else None)
            self._connection_status = (
                ConnectionStatus.DEGRADED
                if self._probe_issue is not None
                else ConnectionStatus.CONNECTED
            )
            self._capabilities = _capability_defaults(family)
            return self.snapshot()

    def mark_disconnected(self) -> OneBotCapabilitySnapshot:
        with self._lock:
            self._generation += 1
            self._adapter_connected = False
            self._connection_status = ConnectionStatus.DISCONNECTED
            self._probe_issue = "disconnected"
            for capability, record in tuple(self._capabilities.items()):
                if record.status in {
                    CapabilityStatus.SUPPORTED,
                    CapabilityStatus.DEGRADED,
                }:
                    self._capabilities[capability] = CapabilityRecord(
                        capability,
                        CapabilityStatus.DEGRADED,
                        "adapter_disconnected",
                    )
            return self.snapshot()

    def mark_probe_failure(self) -> OneBotCapabilitySnapshot:
        with self._lock:
            if self._adapter_connected:
                self._connection_status = ConnectionStatus.DEGRADED
                self._probe_issue = "internal_error"
            return self.snapshot()

    def record_success(
        self,
        capability: Capability | str,
        *,
        generation: int | None = None,
    ) -> None:
        normalized = Capability(capability)
        with self._lock:
            if generation is not None and (
                generation != self._generation or not self._adapter_connected
            ):
                return
            self._capabilities[normalized] = CapabilityRecord(
                normalized,
                CapabilityStatus.SUPPORTED,
                "business_call_success",
            )

    def record_failure(
        self,
        capability: Capability | str,
        *,
        unsupported: bool,
        generation: int | None = None,
    ) -> None:
        normalized = Capability(capability)
        with self._lock:
            if generation is not None and (
                generation != self._generation or not self._adapter_connected
            ):
                return
            self._capabilities[normalized] = CapabilityRecord(
                normalized,
                (
                    CapabilityStatus.UNSUPPORTED
                    if unsupported
                    else CapabilityStatus.DEGRADED
                ),
                (
                    "business_call_unsupported"
                    if unsupported
                    else "business_call_failed"
                ),
            )


onebot_capability_registry = OneBotCapabilityRegistry()


def get_onebot_capability_snapshot() -> OneBotCapabilitySnapshot:
    return onebot_capability_registry.snapshot()


def get_capability_status(capability: Capability | str) -> CapabilityStatus:
    return get_onebot_capability_snapshot().capability(capability).status


def _safe_adapter_name(value: Any) -> str:
    text = str(value or "").strip()
    return text if _is_safe_name(text) else "OneBot V11"


def _is_safe_name(text: str) -> bool:
    normalized = text.casefold()
    return bool(
        _SAFE_NAME_RE.fullmatch(text)
        and any(character.isalpha() for character in text)
        and not any(marker in normalized for marker in _SENSITIVE_NAME_MARKERS)
    )


def _safe_version_text(value: Any) -> str:
    text = str(value or "").strip()
    if not _SAFE_VERSION_RE.fullmatch(text) or (text.isdigit() and len(text) > 6):
        raise ValueError("invalid_version_text")
    return text


def _api_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid_response")
    nested = value.get("data")
    if isinstance(nested, dict):
        return nested
    return value


def _implementation_family(app_name: str) -> ImplementationFamily:
    normalized = re.sub(r"[^a-z0-9]+", "", app_name.casefold())
    if "napcat" in normalized:
        return ImplementationFamily.NAPCAT
    if normalized in {"onebot", "onebot11", "onebotv11", "genericonebot"}:
        return ImplementationFamily.ONEBOT
    return ImplementationFamily.UNKNOWN


def _parse_version_info(value: Any) -> ImplementationInfo:
    payload = _api_payload(value)
    name = str(payload.get("app_name") or "").strip()
    if not _is_safe_name(name):
        raise ValueError("invalid_implementation_name")
    version = _safe_version_text(payload.get("app_version"))
    protocol_version = _safe_version_text(payload.get("protocol_version"))
    return ImplementationInfo(
        name=name,
        version=version,
        protocol_version=protocol_version,
        family=_implementation_family(name),
    )


def _parse_health(value: Any) -> bool:
    payload = _api_payload(value)
    online = payload.get("online")
    good = payload.get("good")
    if online is not None and not isinstance(online, bool):
        raise ValueError("invalid_online_status")
    if good is not None and not isinstance(good, bool):
        raise ValueError("invalid_good_status")
    if online is None and good is None:
        raise ValueError("missing_health_status")
    return online is not False and good is not False


@dataclass(frozen=True)
class _ProbeOutcome:
    value: Any = None
    issue: str | None = None


async def _probe_action(bot: Any, action: str, timeout: float) -> _ProbeOutcome:
    try:
        return _ProbeOutcome(
            value=await asyncio.wait_for(bot.call_api(action), timeout=timeout)
        )
    except asyncio.TimeoutError:
        return _ProbeOutcome(issue="timeout")
    except Exception:
        return _ProbeOutcome(issue="api_error")


def _merge_probe_issues(*issues: str | None) -> str | None:
    present = {issue for issue in issues if issue}
    for issue in ("timeout", "api_error", "invalid_response"):
        if issue in present:
            return issue
    return None


def _adapter_name_from_bot(bot: Any) -> str:
    try:
        return _safe_adapter_name(bot.adapter.get_name())
    except Exception:
        return "OneBot V11"


async def probe_onebot_connection(
    bot: Any,
    *,
    registry: OneBotCapabilityRegistry = onebot_capability_registry,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> OneBotCapabilitySnapshot:
    """Probe a connected OneBot implementation using read-only standard APIs only."""
    generation = registry.begin_connection(_adapter_name_from_bot(bot))
    version_outcome, status_outcome = await asyncio.gather(
        *(
            _probe_action(bot, action, timeout)
            for action in READ_ONLY_PROBE_ACTIONS
        )
    )

    implementation: ImplementationInfo | None = None
    healthy: bool | None = None
    version_issue = version_outcome.issue
    status_issue = status_outcome.issue
    if version_issue is None:
        try:
            implementation = _parse_version_info(version_outcome.value)
        except (TypeError, ValueError):
            version_issue = "invalid_response"
    if status_issue is None:
        try:
            healthy = _parse_health(status_outcome.value)
        except (TypeError, ValueError):
            status_issue = "invalid_response"

    issue = _merge_probe_issues(version_issue, status_issue)
    snapshot = registry.apply_probe(
        generation,
        implementation,
        healthy=healthy,
        issue=issue,
    )
    if issue:
        logger.warning("OneBot 只读能力探测未完整完成 issue=%s", issue)
    else:
        logger.info(
            "OneBot 能力已登记 adapter=%s implementation=%s version=%s status=%s",
            snapshot.adapter_name,
            snapshot.implementation_name or "unknown",
            snapshot.implementation_version or "unknown",
            snapshot.connection_status.value,
        )
    return snapshot


async def handle_onebot_connect(bot: Bot) -> None:
    try:
        await probe_onebot_connection(bot)
    except Exception:
        # Connection hooks must never prevent the adapter or bot from starting.
        onebot_capability_registry.mark_probe_failure()
        logger.exception("OneBot 连接能力登记发生未预期异常，机器人继续启动")


async def handle_onebot_disconnect(bot: Bot) -> None:
    onebot_capability_registry.mark_disconnected()
    logger.warning("OneBot 适配器连接已断开")


_registered_driver_ids: set[int] = set()


def register_onebot_capability_hooks(driver: Any) -> None:
    driver_id = id(driver)
    if driver_id in _registered_driver_ids:
        return
    driver.on_bot_connect(handle_onebot_connect)
    driver.on_bot_disconnect(handle_onebot_disconnect)
    _registered_driver_ids.add(driver_id)


def _looks_unsupported(exc: Exception) -> bool:
    values = [str(exc)]
    info = getattr(exc, "info", None)
    if isinstance(info, dict):
        values.extend(str(value) for value in info.values())
    normalized = " ".join(values).casefold()
    return any(marker in normalized for marker in _UNSUPPORTED_MARKERS)


async def call_capability_api(
    bot: Any,
    capability: Capability | str,
    action: str,
    *,
    registry: OneBotCapabilityRegistry = onebot_capability_registry,
    **params: Any,
) -> Any:
    """Call a business API and update only its declared capability state."""
    normalized = Capability(capability)
    if action not in CAPABILITY_ACTIONS[normalized]:
        raise ValueError(f"action_not_registered:{normalized.value}:{action}")

    snapshot = registry.snapshot()
    record = snapshot.capability(normalized)
    if not snapshot.adapter_connected:
        raise CapabilityUnavailable(normalized, CapabilityStatus.DEGRADED)
    if record.status is CapabilityStatus.UNSUPPORTED:
        raise CapabilityUnavailable(normalized, record.status)

    try:
        result = await bot.call_api(action, **params)
    except Exception as exc:
        registry.record_failure(
            normalized,
            unsupported=_looks_unsupported(exc),
            generation=snapshot.generation,
        )
        raise
    registry.record_success(normalized, generation=snapshot.generation)
    return result
