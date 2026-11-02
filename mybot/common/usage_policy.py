from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import threading
import time
from typing import Any

from mybot.common.accounting import ASSET_POINTS, get_balance
from mybot.common.paid_rounds import (
    STATE_ACTIVE,
    STATE_EXPIRED,
    STATE_PREPARING,
    STATE_REFUNDED,
    STATE_REFUNDING,
    STATE_SETTLED,
    STATE_SETTLING,
    PaidRoundService,
    new_round_id,
    register_recovery_adapter,
)


class QuotaScope(StrEnum):
    USER = "user"
    GROUP = "group"
    FEATURE = "feature"


@dataclass(frozen=True)
class WindowQuota:
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("quota_limit_must_be_positive")
        if self.window_seconds <= 0:
            raise ValueError("quota_window_must_be_positive")


@dataclass(frozen=True)
class QuotaPlan:
    user: WindowQuota | None = None
    group: WindowQuota | None = None
    feature: WindowQuota | None = None


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    wait_seconds: int = 0
    blocked_scope: QuotaScope | None = None
    remaining: dict[QuotaScope, int] | None = None


HISTORY_GAME_QUOTA = QuotaPlan(
    user=WindowQuota(10, 300),
    group=WindowQuota(60, 300),
    feature=WindowQuota(300, 300),
)
AI_REQUEST_QUOTA = QuotaPlan(
    user=WindowQuota(6, 60),
    group=WindowQuota(30, 60),
    feature=WindowQuota(120, 60),
)


_quota_lock = threading.RLock()
quota_records: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)


def scaled_quota_plan(user_limit: int, window_seconds: int) -> QuotaPlan:
    """Build a three-level plan while retaining a feature's user-facing limit."""
    return QuotaPlan(
        user=WindowQuota(user_limit, window_seconds),
        group=WindowQuota(max(user_limit * 5, user_limit), window_seconds),
        feature=WindowQuota(max(user_limit * 20, user_limit), window_seconds),
    )


def _quota_buckets(
    feature_key: str,
    user_id: str,
    group_id: str | None,
    plan: QuotaPlan,
) -> list[tuple[QuotaScope, str, WindowQuota]]:
    feature_key = str(feature_key).strip()
    user_id = str(user_id).strip()
    normalized_group = str(group_id).strip() if group_id is not None else ""
    if not feature_key:
        raise ValueError("feature_key_required")
    if not user_id:
        raise ValueError("user_id_required")

    buckets: list[tuple[QuotaScope, str, WindowQuota]] = []
    if plan.user is not None:
        user_scope = f"{normalized_group or 'private'}:{user_id}"
        buckets.append((QuotaScope.USER, user_scope, plan.user))
    if plan.group is not None and normalized_group:
        buckets.append((QuotaScope.GROUP, normalized_group, plan.group))
    if plan.feature is not None:
        buckets.append((QuotaScope.FEATURE, feature_key, plan.feature))
    return buckets


def consume_quota(
    feature_key: str,
    user_id: str,
    group_id: str | None,
    plan: QuotaPlan,
    *,
    now: float | None = None,
) -> QuotaDecision:
    """Atomically consume user, group and feature rolling-window quotas."""
    current_time = time.monotonic() if now is None else float(now)
    buckets = _quota_buckets(feature_key, user_id, group_id, plan)

    with _quota_lock:
        blocked: list[tuple[QuotaScope, int]] = []
        prepared: list[tuple[QuotaScope, deque[float], WindowQuota]] = []
        for scope, identity, rule in buckets:
            records = quota_records[(feature_key, scope.value, identity)]
            while records and current_time - records[0] >= rule.window_seconds:
                records.popleft()
            if len(records) >= rule.limit:
                wait_seconds = max(
                    1,
                    int(rule.window_seconds - (current_time - records[0]) + 0.999),
                )
                blocked.append((scope, wait_seconds))
            prepared.append((scope, records, rule))

        if blocked:
            scope, wait_seconds = max(blocked, key=lambda item: item[1])
            return QuotaDecision(
                allowed=False,
                wait_seconds=wait_seconds,
                blocked_scope=scope,
                remaining={
                    item_scope: max(0, rule.limit - len(records))
                    for item_scope, records, rule in prepared
                },
            )

        remaining: dict[QuotaScope, int] = {}
        for scope, records, rule in prepared:
            records.append(current_time)
            remaining[scope] = max(0, rule.limit - len(records))
        return QuotaDecision(allowed=True, remaining=remaining)


def clear_quota_records() -> None:
    with _quota_lock:
        quota_records.clear()


def quota_wait_message(decision: QuotaDecision) -> str:
    wait_seconds = max(1, int(decision.wait_seconds))
    return (
        f"（按住尚未干透的墨页）今夜落笔太密，且歇 {wait_seconds} 秒再来。\n"
        "『好句也须留一息，风清墨定再开篇。』"
    )


class UsageQuotaExceeded(RuntimeError):
    def __init__(self, decision: QuotaDecision):
        super().__init__("usage_quota_exceeded")
        self.decision = decision


class PaidOperationError(RuntimeError):
    pass


class PaidOperationInsufficientBalance(PaidOperationError):
    def __init__(self, balance: int):
        super().__init__("paid_operation_insufficient_balance")
        self.balance = int(balance)


class PaidOperationExpired(PaidOperationError):
    pass


class PaidOperationStateError(PaidOperationError):
    pass


OPERATION_AWAITING_CONFIRMATION = "awaiting_confirmation"
OPERATION_PROCESSING = "processing"
OPERATION_COMPLETED = "completed"
OPERATION_REFUNDING = "refunding"
OPERATION_REFUNDED = "refunded"
OPERATION_CANCELLED = "cancelled"
PAID_OPERATION_GAME_TYPE = "shared_paid_operation"


@dataclass(frozen=True)
class PaidOperationSnapshot:
    operation_id: str
    feature_key: str
    user_id: str
    group_id: str
    cost: int
    status: str
    balance: int
    existing: bool
    record: dict[str, Any]


_paid_operation_lock = threading.RLock()
_loaded_paid_operations: set[str] = set()


def request_fingerprint(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _operation_payload(round_record: dict[str, Any]) -> dict[str, Any]:
    payload = round_record.get("payload", {})
    operation = payload.get("paid_operation", {}) if isinstance(payload, dict) else {}
    return operation if isinstance(operation, dict) else {}


def _operation_status(round_record: dict[str, Any]) -> str:
    state = round_record.get("state")
    operation = _operation_payload(round_record)
    if state == STATE_PREPARING and operation.get("confirmation_required"):
        return OPERATION_AWAITING_CONFIRMATION
    if state in {STATE_PREPARING, STATE_ACTIVE, STATE_SETTLING}:
        return OPERATION_PROCESSING
    if state == STATE_SETTLED:
        return OPERATION_COMPLETED
    if state == STATE_REFUNDING:
        return OPERATION_REFUNDING
    if state == STATE_REFUNDED:
        return OPERATION_REFUNDED
    if state == STATE_EXPIRED:
        return OPERATION_CANCELLED
    raise PaidOperationError("unsupported_paid_operation_state")


class PaidOperationService:
    """Single-participant paid work built on the durable paid-round ledger."""

    def __init__(self, round_service: PaidRoundService | None = None):
        self.round_service = round_service or PaidRoundService()

    def _balance(self, round_record: dict[str, Any]) -> int:
        participant = next(iter(round_record.get("participants", {}).values()), None)
        if not isinstance(participant, dict):
            return 0
        asset_type = str(round_record.get("asset_type") or ASSET_POINTS)
        return get_balance(
            asset_type,
            participant["user_id"],
            round_record["group_id"],
            store_path=self.round_service._ledger_path(asset_type),
        )

    def _snapshot(self, round_record: dict[str, Any], *, existing: bool) -> PaidOperationSnapshot:
        operation = _operation_payload(round_record)
        participant = next(iter(round_record.get("participants", {}).values()), {})
        return PaidOperationSnapshot(
            operation_id=round_record["round_id"],
            feature_key=str(round_record.get("feature_key") or operation.get("feature_key") or ""),
            user_id=str(participant.get("user_id") or round_record.get("creator_id") or ""),
            group_id=str(round_record.get("group_id") or ""),
            cost=int(operation.get("cost") or participant.get("amount") or 0),
            status=_operation_status(round_record),
            balance=self._balance(round_record),
            existing=existing,
            record=round_record,
        )

    def _find_unfinished(
        self,
        *,
        feature_key: str,
        user_id: str,
        group_id: str,
        fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        fallback = None
        for round_record in self.round_service.list_rounds(unfinished_only=True):
            if round_record.get("game_type") != PAID_OPERATION_GAME_TYPE:
                continue
            if str(round_record.get("feature_key") or "") != feature_key:
                continue
            if str(round_record.get("group_id") or "") != group_id:
                continue
            participant = next(iter(round_record.get("participants", {}).values()), {})
            if str(participant.get("user_id") or "") != user_id:
                continue
            operation = _operation_payload(round_record)
            if fingerprint and operation.get("request_fingerprint") == fingerprint:
                return round_record
            fallback = fallback or round_record
        return fallback

    def begin(
        self,
        *,
        feature_key: str,
        user_id: str,
        group_id: str,
        cost: int,
        request_key: str,
        confirmation_required: bool = False,
        ttl_seconds: int = 180,
        quota_plan: QuotaPlan | None = None,
        now: float | None = None,
    ) -> PaidOperationSnapshot:
        feature_key = str(feature_key).strip()
        user_id = str(user_id).strip()
        group_id = str(group_id).strip()
        if not feature_key or not user_id or not group_id:
            raise ValueError("paid_operation_identity_required")
        if int(cost) <= 0:
            raise ValueError("paid_operation_cost_must_be_positive")
        if int(ttl_seconds) <= 0:
            raise ValueError("paid_operation_ttl_must_be_positive")
        fingerprint = request_fingerprint(request_key)
        current_time = time.time() if now is None else float(now)

        with _paid_operation_lock:
            existing = self._find_unfinished(
                feature_key=feature_key,
                user_id=user_id,
                group_id=group_id,
                fingerprint=fingerprint,
            )
            if existing is not None:
                return self._snapshot(existing, existing=True)

            if quota_plan is not None:
                decision = consume_quota(
                    feature_key,
                    user_id,
                    group_id,
                    quota_plan,
                    now=now,
                )
                if not decision.allowed:
                    raise UsageQuotaExceeded(decision)

            operation_id = new_round_id(PAID_OPERATION_GAME_TYPE)
            round_record = self.round_service.create_round(
                round_id=operation_id,
                game_type=PAID_OPERATION_GAME_TYPE,
                mode="one_shot",
                group_id=group_id,
                creator_id=user_id,
                asset_type=ASSET_POINTS,
                feature_key=feature_key,
                payload={
                    "paid_operation": {
                        "feature_key": feature_key,
                        "request_fingerprint": fingerprint,
                        "confirmation_required": bool(confirmation_required),
                        "cost": int(cost),
                    }
                },
                participants=[{"user_id": user_id, "amount": int(cost)}],
                deadline_at=current_time + int(ttl_seconds),
            )
            _loaded_paid_operations.add(operation_id)
            if confirmation_required:
                return self._snapshot(round_record, existing=False)
            return self.confirm(operation_id, now=current_time)

    def find_open(
        self,
        *,
        feature_key: str,
        user_id: str,
        group_id: str,
        request_key: str | None = None,
    ) -> PaidOperationSnapshot | None:
        fingerprint = request_fingerprint(request_key) if request_key is not None else None
        round_record = self._find_unfinished(
            feature_key=str(feature_key).strip(),
            user_id=str(user_id).strip(),
            group_id=str(group_id).strip(),
            fingerprint=fingerprint,
        )
        return self._snapshot(round_record, existing=True) if round_record else None

    def confirm(self, operation_id: str, *, now: float | None = None) -> PaidOperationSnapshot:
        with _paid_operation_lock:
            round_record = self.round_service.get_round(operation_id)
            if round_record.get("state") != STATE_PREPARING:
                return self._snapshot(round_record, existing=True)
            deadline = round_record.get("deadline_at")
            current_time = time.time() if now is None else float(now)
            if deadline is not None and float(deadline) < current_time:
                self.round_service.refund_round(operation_id, reason="confirmation_expired")
                _loaded_paid_operations.discard(operation_id)
                raise PaidOperationExpired("paid_operation_confirmation_expired")

            user_id = str(round_record["creator_id"])
            charge = self.round_service.freeze_participant(operation_id, user_id)
            if not charge["ok"]:
                self.round_service.refund_round(
                    operation_id,
                    reason="insufficient_balance",
                )
                _loaded_paid_operations.discard(operation_id)
                raise PaidOperationInsufficientBalance(int(charge.get("balance", 0)))
            return self._snapshot(self.round_service.get_round(operation_id), existing=False)

    def record_result(self, operation_id: str, *, result_key: str) -> PaidOperationSnapshot:
        with _paid_operation_lock:
            round_record = self.round_service.get_round(operation_id)
            if round_record.get("state") == STATE_SETTLED:
                return self._snapshot(round_record, existing=True)
            if round_record.get("state") in {STATE_REFUNDED, STATE_EXPIRED, STATE_REFUNDING}:
                raise PaidOperationStateError("cannot_record_refunded_operation")
            if round_record.get("state") not in {STATE_ACTIVE, STATE_SETTLING}:
                raise PaidOperationStateError("cannot_record_unconfirmed_operation")
            participant_id = str(round_record["creator_id"])
            self.round_service.prepare_settlement(
                operation_id,
                result={
                    "completed": True,
                    "result_fingerprint": request_fingerprint(result_key),
                },
                payouts={participant_id: 0},
            )
            return self._snapshot(self.round_service.get_round(operation_id), existing=False)

    def complete(self, operation_id: str, *, result_key: str) -> PaidOperationSnapshot:
        with _paid_operation_lock:
            round_record = self.round_service.get_round(operation_id)
            if round_record.get("state") != STATE_SETTLED and round_record.get("result") is None:
                self.record_result(operation_id, result_key=result_key)
            settled = self.round_service.settle_round(operation_id)
            _loaded_paid_operations.discard(operation_id)
            return self._snapshot(settled, existing=False)

    def refund(self, operation_id: str, *, reason: str) -> PaidOperationSnapshot:
        with _paid_operation_lock:
            round_record = self.round_service.get_round(operation_id)
            if round_record.get("state") == STATE_SETTLED:
                return self._snapshot(round_record, existing=True)
            refunded = self.round_service.refund_round(operation_id, reason=reason)
            _loaded_paid_operations.discard(operation_id)
            return self._snapshot(refunded, existing=False)

    def get(self, operation_id: str) -> PaidOperationSnapshot:
        return self._snapshot(self.round_service.get_round(operation_id), existing=True)


def paid_operation_processing_message() -> str:
    return (
        "（按住上一页未干的墨）同一桩事仍在酝酿，本猫记着账，不会重扣。\n"
        "『一卷未成休叠卷，月移半寸自回声。』"
    )


def paid_operation_refund_message(cost: int) -> str:
    return (
        f"（收回未成的墨卷）这一笔没有办成，{int(cost)} 积分已原样归还。\n"
        "『墨未成章钱先返，明灯再起续新篇。』"
    )


def _restore_paid_operation(round_record: dict, service: PaidRoundService) -> None:
    operation_id = round_record["round_id"]
    operation = _operation_payload(round_record)
    if round_record.get("state") == STATE_PREPARING and operation.get("confirmation_required"):
        _loaded_paid_operations.add(operation_id)
        return
    service.refund_round(operation_id, reason="interrupted_before_result")
    _loaded_paid_operations.discard(operation_id)


def _discard_paid_operation(round_record: dict, service: PaidRoundService) -> None:
    _loaded_paid_operations.discard(round_record["round_id"])


def _expire_paid_operation(round_record: dict, service: PaidRoundService) -> None:
    operation_id = round_record["round_id"]
    if round_record.get("result") is not None or round_record.get("state") == STATE_SETTLING:
        service.settle_round(operation_id)
    else:
        service.refund_round(operation_id, reason="operation_deadline_expired")
    _loaded_paid_operations.discard(operation_id)


register_recovery_adapter(
    PAID_OPERATION_GAME_TYPE,
    restore=_restore_paid_operation,
    is_loaded=lambda round_record: round_record["round_id"] in _loaded_paid_operations,
    discard=_discard_paid_operation,
    on_due=_expire_paid_operation,
)
