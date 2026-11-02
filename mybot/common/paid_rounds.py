from __future__ import annotations

import asyncio
import copy
import inspect
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from mybot.common.accounting import (
    ASSET_POINTS,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REFUNDED,
    STATUS_SETTLED,
    credit_balance,
    freeze_balance,
    get_transaction_status,
    refund_transaction,
    settle_transaction,
)
from mybot.common.json_store import load_json, mutate_json
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)

PAID_ROUNDS_FILE = Path(__file__).resolve().parent.parent / "data" / "paid_rounds.json"
PAID_ROUNDS_SCHEMA_VERSION = 1

STATE_PREPARING = "preparing"
STATE_ACTIVE = "active"
STATE_SETTLING = "settling"
STATE_SETTLED = "settled"
STATE_REFUNDING = "refunding"
STATE_REFUNDED = "refunded"
STATE_EXPIRED = "expired"

PARTICIPANT_PREPARING = "preparing"
PARTICIPANT_ACTIVE = "active"
PARTICIPANT_SETTLED = "settled"
PARTICIPANT_REFUNDED = "refunded"
PARTICIPANT_CANCELLED = "cancelled"

TERMINAL_STATES = {STATE_SETTLED, STATE_REFUNDED, STATE_EXPIRED}
RECOVERY_INTERVAL_SECONDS = 5


class PaidRoundError(RuntimeError):
    """Base exception for unsafe or conflicting paid-round operations."""


class PaidRoundNotFoundError(PaidRoundError):
    """Raised when a paid round or participant cannot be found."""


class PaidRoundConflictError(PaidRoundError):
    """Raised when a stable round id is reused with conflicting data."""


class PaidRoundStateError(PaidRoundError):
    """Raised when a round cannot safely enter the requested state."""


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_text(value: Any, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise PaidRoundConflictError(f"{field} must not be empty")
    return normalized


def _normalize_amount(value: Any, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise PaidRoundConflictError("amount must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise PaidRoundConflictError("amount must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if normalized < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise PaidRoundConflictError(f"amount must be a {qualifier} integer")
    return normalized


def new_round_id(game_type: str) -> str:
    return f"{_normalize_text(game_type, 'game_type')}:{uuid4().hex}"


def next_local_midnight_timestamp(now: datetime | None = None) -> float:
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    tomorrow = current.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=current.tzinfo).timestamp()


def _default_store() -> dict:
    return {"version": PAID_ROUNDS_SCHEMA_VERSION, "rounds": {}}


def _copy_round(round_record: dict) -> dict:
    return copy.deepcopy(round_record)


def _new_participant(
    round_id: str,
    participant_id: str,
    user_id: str,
    amount: int,
    business_type: str,
    metadata: dict | None = None,
    payout_amount: int = 0,
) -> dict:
    participant_id = _normalize_text(participant_id, "participant_id")
    user_id = _normalize_text(user_id, "user_id")
    return {
        "participant_id": participant_id,
        "user_id": user_id,
        "amount": _normalize_amount(amount),
        "stake_tx_id": f"round:{round_id}:stake:{participant_id}",
        "payout_tx_id": f"round:{round_id}:payout:{participant_id}",
        "business_type": _normalize_text(business_type, "business_type"),
        "state": PARTICIPANT_PREPARING,
        "payout_amount": _normalize_amount(payout_amount, allow_zero=True),
        "metadata": copy.deepcopy(metadata or {}),
        "updated_at": _now_text(),
    }


class PaidRoundService:
    """Versioned paid-round state coupled to the v0.4.1 accounting service.

    The round document deliberately stores only recovery inputs and stable
    accounting transaction ids. Ledger balances remain authoritative in their
    existing JSON stores.
    """

    def __init__(
        self,
        store_path: Path | str | None = None,
        *,
        ledger_paths: dict[str, Path | str] | None = None,
    ):
        self.store_path = Path(store_path) if store_path is not None else PAID_ROUNDS_FILE
        self.ledger_paths = {
            asset_type: Path(path)
            for asset_type, path in (ledger_paths or {}).items()
        }

    def _ledger_path(self, asset_type: str) -> Path | None:
        return self.ledger_paths.get(asset_type)

    @staticmethod
    def _rounds(data: dict, *, create: bool = False) -> dict:
        if not isinstance(data, dict):
            raise PaidRoundConflictError("paid-round store must be an object")
        rounds = data.get("rounds")
        if rounds is None and create:
            rounds = {}
            data["rounds"] = rounds
            data.setdefault("version", PAID_ROUNDS_SCHEMA_VERSION)
        if not isinstance(rounds, dict):
            raise PaidRoundConflictError("paid-round collection must be an object")
        return rounds

    @staticmethod
    def _require_round(data: dict, round_id: str) -> dict:
        round_record = PaidRoundService._rounds(data, create=False).get(round_id)
        if not isinstance(round_record, dict):
            raise PaidRoundNotFoundError(f"paid round not found: {round_id}")
        return round_record

    @staticmethod
    def _require_participant(round_record: dict, participant_id: str) -> dict:
        participants = round_record.get("participants")
        if not isinstance(participants, dict):
            raise PaidRoundConflictError("round participants must be an object")
        participant = participants.get(participant_id)
        if not isinstance(participant, dict):
            raise PaidRoundNotFoundError(
                f"paid round participant not found: {round_record.get('round_id')}:{participant_id}"
            )
        return participant

    @staticmethod
    def _touch(round_record: dict) -> None:
        round_record["updated_at"] = _now_text()
        round_record["version"] = int(round_record.get("version", 0)) + 1

    def create_round(
        self,
        *,
        round_id: str,
        game_type: str,
        mode: str,
        group_id: str,
        creator_id: str,
        asset_type: str = ASSET_POINTS,
        feature_key: str | None = None,
        payload: dict | None = None,
        participants: list[dict] | None = None,
        deadline_at: float | None = None,
        result: dict | None = None,
    ) -> dict:
        round_id = _normalize_text(round_id, "round_id")
        game_type = _normalize_text(game_type, "game_type")
        group_id = _normalize_text(group_id, "group_id")
        creator_id = _normalize_text(creator_id, "creator_id")
        business_type = f"paid_round:{game_type}"
        participant_records: dict[str, dict] = {}
        for item in participants or []:
            participant_id = _normalize_text(
                item.get("participant_id", item.get("user_id")),
                "participant_id",
            )
            if participant_id in participant_records:
                raise PaidRoundConflictError(f"duplicate participant: {participant_id}")
            participant_records[participant_id] = _new_participant(
                round_id,
                participant_id,
                item.get("user_id"),
                item.get("amount"),
                business_type,
                item.get("metadata"),
                item.get("payout_amount", 0),
            )

        timestamp = _now_text()
        record = {
            "round_id": round_id,
            "game_type": game_type,
            "mode": _normalize_text(mode, "mode"),
            "feature_key": str(feature_key).strip() if feature_key else None,
            "group_id": group_id,
            "creator_id": creator_id,
            "asset_type": _normalize_text(asset_type, "asset_type"),
            "participants": participant_records,
            "payload": copy.deepcopy(payload or {}),
            "result": copy.deepcopy(result),
            "state": STATE_PREPARING if participant_records else STATE_ACTIVE,
            "schema_version": PAID_ROUNDS_SCHEMA_VERSION,
            "version": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "deadline_at": float(deadline_at) if deadline_at is not None else None,
        }

        def mutator(data: dict) -> dict:
            rounds = self._rounds(data, create=True)
            existing = rounds.get(round_id)
            if existing is not None:
                comparable_fields = (
                    "round_id",
                    "game_type",
                    "mode",
                    "feature_key",
                    "group_id",
                    "creator_id",
                    "asset_type",
                )
                if not isinstance(existing, dict) or any(
                    existing.get(field) != record.get(field) for field in comparable_fields
                ):
                    raise PaidRoundConflictError(f"conflicting paid round: {round_id}")
                return _copy_round(existing)
            rounds[round_id] = record
            return _copy_round(record)

        return mutate_json(self.store_path, _default_store(), mutator)

    def get_round(self, round_id: str) -> dict:
        round_id = _normalize_text(round_id, "round_id")
        data = load_json(self.store_path, _default_store())
        return _copy_round(self._require_round(data, round_id))

    def list_rounds(self, *, unfinished_only: bool = False) -> list[dict]:
        data = load_json(self.store_path, _default_store())
        rounds = self._rounds(data, create=False)
        values = []
        for round_record in rounds.values():
            if not isinstance(round_record, dict):
                raise PaidRoundConflictError("paid-round entry must be an object")
            if unfinished_only and round_record.get("state") in TERMINAL_STATES:
                continue
            values.append(_copy_round(round_record))
        values.sort(key=lambda item: (item.get("created_at", ""), item.get("round_id", "")))
        return values

    def add_participant(
        self,
        round_id: str,
        *,
        participant_id: str,
        user_id: str,
        amount: int,
        metadata: dict | None = None,
        payout_amount: int = 0,
    ) -> dict:
        round_id = _normalize_text(round_id, "round_id")
        participant_id = _normalize_text(participant_id, "participant_id")

        def mutator(data: dict) -> dict:
            round_record = self._require_round(data, round_id)
            if round_record.get("state") in TERMINAL_STATES | {STATE_REFUNDING, STATE_SETTLING}:
                raise PaidRoundStateError(f"cannot join paid round in state {round_record.get('state')}")
            participants = round_record.setdefault("participants", {})
            existing = participants.get(participant_id)
            business_type = f"paid_round:{round_record['game_type']}"
            candidate = _new_participant(
                round_id,
                participant_id,
                user_id,
                amount,
                business_type,
                metadata,
                payout_amount,
            )
            if existing is not None:
                comparable = ("participant_id", "user_id", "amount", "stake_tx_id", "payout_tx_id")
                if not isinstance(existing, dict) or any(
                    existing.get(field) != candidate.get(field) for field in comparable
                ):
                    raise PaidRoundConflictError(
                        f"conflicting paid round participant: {round_id}:{participant_id}"
                    )
                return copy.deepcopy(existing)
            participants[participant_id] = candidate
            self._touch(round_record)
            return copy.deepcopy(candidate)

        return mutate_json(self.store_path, _default_store(), mutator)

    def _update_participant_state(
        self,
        round_id: str,
        participant_id: str,
        state: str,
        *,
        activate_round: bool = False,
    ) -> dict:
        def mutator(data: dict) -> dict:
            round_record = self._require_round(data, round_id)
            participant = self._require_participant(round_record, participant_id)
            participant["state"] = state
            participant["updated_at"] = _now_text()
            if activate_round and round_record.get("state") == STATE_PREPARING:
                round_record["state"] = STATE_ACTIVE
            self._touch(round_record)
            return copy.deepcopy(participant)

        return mutate_json(self.store_path, _default_store(), mutator)

    def freeze_participant(self, round_id: str, participant_id: str) -> dict:
        round_record = self.get_round(round_id)
        participant = self._require_participant(round_record, participant_id)
        asset_type = round_record["asset_type"]
        ledger_path = self._ledger_path(asset_type)
        result = freeze_balance(
            participant["stake_tx_id"],
            asset_type,
            participant["user_id"],
            round_record["group_id"],
            participant["amount"],
            participant["business_type"],
            store_path=ledger_path,
        )
        state = PARTICIPANT_ACTIVE if result["ok"] else PARTICIPANT_CANCELLED
        self._update_participant_state(
            round_id,
            participant_id,
            state,
            activate_round=result["ok"],
        )
        return result

    def update_payload(self, round_id: str, payload: dict) -> dict:
        round_id = _normalize_text(round_id, "round_id")

        def mutator(data: dict) -> dict:
            round_record = self._require_round(data, round_id)
            if round_record.get("state") in TERMINAL_STATES:
                raise PaidRoundStateError("cannot update a terminal paid round")
            round_record["payload"] = copy.deepcopy(payload)
            self._touch(round_record)
            return _copy_round(round_record)

        return mutate_json(self.store_path, _default_store(), mutator)

    def prepare_settlement(
        self,
        round_id: str,
        *,
        result: dict,
        payouts: dict[str, int] | None = None,
    ) -> dict:
        round_id = _normalize_text(round_id, "round_id")
        normalized_payouts = {
            _normalize_text(participant_id, "participant_id"): _normalize_amount(
                amount,
                allow_zero=True,
            )
            for participant_id, amount in (payouts or {}).items()
        }

        def mutator(data: dict) -> dict:
            round_record = self._require_round(data, round_id)
            if round_record.get("state") == STATE_SETTLED:
                return _copy_round(round_record)
            if round_record.get("state") in {STATE_REFUNDING, STATE_REFUNDED, STATE_EXPIRED}:
                raise PaidRoundStateError(f"cannot settle paid round in state {round_record.get('state')}")
            participants = round_record.get("participants", {})
            unknown = set(normalized_payouts) - set(participants)
            if unknown:
                raise PaidRoundConflictError(f"unknown payout participants: {sorted(unknown)}")
            existing_result = round_record.get("result")
            if existing_result is not None and existing_result != result:
                raise PaidRoundConflictError(f"conflicting paid round result: {round_id}")
            round_record["result"] = copy.deepcopy(result)
            for participant_id, participant in participants.items():
                amount = normalized_payouts.get(participant_id, participant.get("payout_amount", 0))
                existing_amount = _normalize_amount(
                    participant.get("payout_amount", 0),
                    allow_zero=True,
                )
                if existing_amount not in {0, amount}:
                    raise PaidRoundConflictError(
                        f"conflicting paid round payout: {round_id}:{participant_id}"
                    )
                participant["payout_amount"] = amount
                participant["updated_at"] = _now_text()
            round_record["state"] = STATE_SETTLING
            self._touch(round_record)
            return _copy_round(round_record)

        return mutate_json(self.store_path, _default_store(), mutator)

    def _participant_expected(self, round_record: dict, participant: dict) -> dict:
        return {
            "user_id": participant["user_id"],
            "group_id": round_record["group_id"],
            "amount": participant["amount"],
            "business_type": participant["business_type"],
        }

    def settle_participant(
        self,
        round_id: str,
        participant_id: str,
        *,
        payout_amount: int | None = None,
    ) -> dict:
        if payout_amount is not None:
            normalized_payout = _normalize_amount(payout_amount, allow_zero=True)

            def payout_mutator(data: dict) -> None:
                round_record = self._require_round(data, round_id)
                participant = self._require_participant(round_record, participant_id)
                current = _normalize_amount(participant.get("payout_amount", 0), allow_zero=True)
                if current not in {0, normalized_payout}:
                    raise PaidRoundConflictError(
                        f"conflicting paid round payout: {round_id}:{participant_id}"
                    )
                participant["payout_amount"] = normalized_payout
                participant["updated_at"] = _now_text()
                self._touch(round_record)

            mutate_json(self.store_path, _default_store(), payout_mutator)

        round_record = self.get_round(round_id)
        participant = self._require_participant(round_record, participant_id)
        asset_type = round_record["asset_type"]
        ledger_path = self._ledger_path(asset_type)
        tx_status = get_transaction_status(
            participant["stake_tx_id"],
            asset_type,
            store_path=ledger_path,
        )
        if tx_status is None:
            updated = self._update_participant_state(
                round_id,
                participant_id,
                PARTICIPANT_CANCELLED,
            )
            return {"status": PARTICIPANT_CANCELLED, "participant": updated}
        if tx_status == STATUS_PENDING:
            settle_transaction(
                participant["stake_tx_id"],
                asset_type,
                store_path=ledger_path,
                **self._participant_expected(round_record, participant),
            )
        elif tx_status == STATUS_CANCELLED:
            updated = self._update_participant_state(
                round_id,
                participant_id,
                PARTICIPANT_CANCELLED,
            )
            return {"status": PARTICIPANT_CANCELLED, "participant": updated}
        elif tx_status == STATUS_REFUNDED:
            updated = self._update_participant_state(
                round_id,
                participant_id,
                PARTICIPANT_REFUNDED,
            )
            return {"status": PARTICIPANT_REFUNDED, "participant": updated}
        elif tx_status != STATUS_SETTLED:
            raise PaidRoundStateError(f"unsupported stake transaction state: {tx_status}")

        payout = _normalize_amount(participant.get("payout_amount", 0), allow_zero=True)
        payout_result = None
        if payout > 0:
            payout_result = credit_balance(
                participant["payout_tx_id"],
                asset_type,
                participant["user_id"],
                round_record["group_id"],
                payout,
                f"paid_round:{round_record['game_type']}:payout",
                store_path=ledger_path,
            )
        updated = self._update_participant_state(
            round_id,
            participant_id,
            PARTICIPANT_SETTLED,
        )
        return {
            "status": PARTICIPANT_SETTLED,
            "participant": updated,
            "payout": payout_result,
        }

    def settle_round(self, round_id: str) -> dict:
        round_record = self.get_round(round_id)
        if round_record.get("state") == STATE_SETTLED:
            return round_record
        if round_record.get("result") is None:
            raise PaidRoundStateError(f"paid round has no persisted result: {round_id}")
        if round_record.get("state") != STATE_SETTLING:
            round_record = self.prepare_settlement(
                round_id,
                result=round_record["result"],
                payouts={
                    participant_id: participant.get("payout_amount", 0)
                    for participant_id, participant in round_record.get("participants", {}).items()
                },
            )

        for participant_id in list(round_record.get("participants", {})):
            self.settle_participant(round_id, participant_id)

        def mutator(data: dict) -> dict:
            stored = self._require_round(data, round_id)
            participant_states = {
                participant.get("state")
                for participant in stored.get("participants", {}).values()
            }
            if not participant_states.issubset(
                {PARTICIPANT_SETTLED, PARTICIPANT_CANCELLED, PARTICIPANT_REFUNDED}
            ):
                raise PaidRoundStateError(f"paid round settlement is incomplete: {round_id}")
            stored["state"] = STATE_SETTLED
            self._touch(stored)
            return _copy_round(stored)

        return mutate_json(self.store_path, _default_store(), mutator)

    def refund_round(self, round_id: str, *, reason: str) -> dict:
        round_record = self.get_round(round_id)
        if round_record.get("state") in {STATE_REFUNDED, STATE_EXPIRED}:
            return round_record
        if round_record.get("state") == STATE_SETTLED:
            raise PaidRoundStateError(f"cannot refund settled paid round: {round_id}")

        def start_refund(data: dict) -> dict:
            stored = self._require_round(data, round_id)
            stored["state"] = STATE_REFUNDING
            stored["refund_reason"] = _normalize_text(reason, "reason")
            self._touch(stored)
            return _copy_round(stored)

        round_record = mutate_json(self.store_path, _default_store(), start_refund)
        asset_type = round_record["asset_type"]
        ledger_path = self._ledger_path(asset_type)

        for participant_id in list(round_record.get("participants", {})):
            current = self.get_round(round_id)
            participant = self._require_participant(current, participant_id)
            tx_status = get_transaction_status(
                participant["stake_tx_id"],
                asset_type,
                store_path=ledger_path,
            )
            target_state = participant.get("state")
            if tx_status is None or tx_status == STATUS_CANCELLED:
                target_state = PARTICIPANT_CANCELLED
            elif tx_status == STATUS_PENDING:
                refund_transaction(
                    participant["stake_tx_id"],
                    asset_type,
                    store_path=ledger_path,
                    **self._participant_expected(current, participant),
                )
                target_state = PARTICIPANT_REFUNDED
            elif tx_status == STATUS_REFUNDED:
                target_state = PARTICIPANT_REFUNDED
            elif tx_status == STATUS_SETTLED:
                if participant.get("metadata", {}).get("role") != "auxiliary":
                    raise PaidRoundStateError(
                        f"cannot refund settled stake without a result: {round_id}:{participant_id}"
                    )
                target_state = PARTICIPANT_SETTLED
            else:
                raise PaidRoundStateError(f"unsupported stake transaction state: {tx_status}")
            self._update_participant_state(round_id, participant_id, target_state)

        def finish_refund(data: dict) -> dict:
            stored = self._require_round(data, round_id)
            stored["state"] = STATE_REFUNDED
            self._touch(stored)
            return _copy_round(stored)

        return mutate_json(self.store_path, _default_store(), finish_refund)

    def expire_round(self, round_id: str, *, reason: str) -> dict:
        def mutator(data: dict) -> dict:
            round_record = self._require_round(data, round_id)
            if round_record.get("state") == STATE_SETTLED:
                raise PaidRoundStateError("cannot expire a settled paid round")
            round_record["state"] = STATE_EXPIRED
            round_record["expire_reason"] = _normalize_text(reason, "reason")
            self._touch(round_record)
            return _copy_round(round_record)

        return mutate_json(self.store_path, _default_store(), mutator)

    def reconcile_participants(self, round_id: str, *, now: float | None = None) -> dict:
        round_record = self.get_round(round_id)
        if round_record.get("state") in TERMINAL_STATES:
            return round_record
        payload = round_record.get("payload", {})
        paid_operation = payload.get("paid_operation", {}) if isinstance(payload, dict) else {}
        deadline = round_record.get("deadline_at")
        if (
            round_record.get("state") == STATE_PREPARING
            and isinstance(paid_operation, dict)
            and paid_operation.get("confirmation_required")
            and deadline is not None
            and float(deadline) > (time.time() if now is None else float(now))
        ):
            return round_record
        asset_type = round_record["asset_type"]
        ledger_path = self._ledger_path(asset_type)
        for participant_id, participant in round_record.get("participants", {}).items():
            if participant.get("state") != PARTICIPANT_PREPARING:
                continue
            tx_status = get_transaction_status(
                participant["stake_tx_id"],
                asset_type,
                store_path=ledger_path,
            )
            state_by_tx = {
                None: PARTICIPANT_CANCELLED,
                STATUS_PENDING: PARTICIPANT_ACTIVE,
                STATUS_SETTLED: PARTICIPANT_SETTLED,
                STATUS_REFUNDED: PARTICIPANT_REFUNDED,
                STATUS_CANCELLED: PARTICIPANT_CANCELLED,
            }
            target = state_by_tx.get(tx_status)
            if target is None:
                raise PaidRoundStateError(f"unsupported stake transaction state: {tx_status}")
            self._update_participant_state(
                round_id,
                participant_id,
                target,
                activate_round=target == PARTICIPANT_ACTIVE,
            )

        round_record = self.get_round(round_id)
        if round_record.get("state") == STATE_PREPARING:
            states = {
                participant.get("state")
                for participant in round_record.get("participants", {}).values()
            }
            if not states or states.issubset({PARTICIPANT_CANCELLED, PARTICIPANT_REFUNDED}):
                return self.expire_round(round_id, reason="never_charged")
        return round_record


RecoveryCallback = Callable[[dict, PaidRoundService], Any]
LoadedCallback = Callable[[dict], bool]


@dataclass(frozen=True)
class RecoveryAdapter:
    restore: RecoveryCallback
    is_loaded: LoadedCallback
    discard: RecoveryCallback
    on_due: RecoveryCallback | None = None


_recovery_adapters: dict[str, RecoveryAdapter] = {}
_hooks_installed = False
_recovery_task: asyncio.Task | None = None


def recovery_hooks_installed() -> bool:
    return _hooks_installed


def register_recovery_adapter(
    game_type: str,
    *,
    restore: RecoveryCallback,
    is_loaded: LoadedCallback,
    discard: RecoveryCallback,
    on_due: RecoveryCallback | None = None,
) -> None:
    normalized = _normalize_text(game_type, "game_type")
    _recovery_adapters[normalized] = RecoveryAdapter(
        restore=restore,
        is_loaded=is_loaded,
        discard=discard,
        on_due=on_due,
    )


async def _invoke(callback: RecoveryCallback, round_record: dict, service: PaidRoundService) -> Any:
    result = callback(_copy_round(round_record), service)
    if inspect.isawaitable(result):
        return await result
    return result


async def recover_unfinished_rounds(
    service: PaidRoundService | None = None,
    *,
    now: float | None = None,
) -> dict[str, str]:
    service = service or PaidRoundService()
    current_time = time.time() if now is None else float(now)
    outcomes: dict[str, str] = {}

    for candidate in service.list_rounds(unfinished_only=True):
        round_id = candidate["round_id"]
        try:
            round_record = service.reconcile_participants(round_id, now=current_time)
            if round_record.get("state") in TERMINAL_STATES:
                adapter = _recovery_adapters.get(round_record.get("game_type"))
                if adapter:
                    await _invoke(adapter.discard, round_record, service)
                outcomes[round_id] = round_record["state"]
                continue

            adapter = _recovery_adapters.get(round_record.get("game_type"))
            loaded = bool(adapter and adapter.is_loaded(round_record))
            feature_key = round_record.get("feature_key")
            enabled = True
            if feature_key:
                from mybot.common.feature_flags import is_feature_enabled

                enabled = is_feature_enabled(feature_key, round_record.get("group_id"))

            if loaded:
                if (
                    not enabled
                    and round_record.get("state") not in {STATE_SETTLING, STATE_REFUNDING}
                    and round_record.get("result") is None
                ):
                    await _invoke(adapter.discard, round_record, service)
                    service.refund_round(round_id, reason="feature_disabled")
                    outcomes[round_id] = STATE_REFUNDED
                    continue
                deadline = round_record.get("deadline_at")
                if deadline is not None and float(deadline) <= current_time and adapter.on_due:
                    await _invoke(adapter.on_due, round_record, service)
                    outcomes[round_id] = service.get_round(round_id)["state"]
                else:
                    outcomes[round_id] = "loaded"
                continue

            if round_record.get("state") == STATE_REFUNDING:
                service.refund_round(
                    round_id,
                    reason=round_record.get("refund_reason") or "resume_refund",
                )
                outcomes[round_id] = STATE_REFUNDED
                continue

            if round_record.get("state") == STATE_SETTLING or round_record.get("result") is not None:
                service.settle_round(round_id)
                outcomes[round_id] = STATE_SETTLED
                continue

            if not enabled:
                if adapter:
                    await _invoke(adapter.discard, round_record, service)
                service.refund_round(round_id, reason="feature_disabled")
                outcomes[round_id] = STATE_REFUNDED
                continue

            deadline = round_record.get("deadline_at")
            if deadline is not None and float(deadline) <= current_time:
                if adapter and adapter.on_due:
                    await _invoke(adapter.on_due, round_record, service)
                    outcomes[round_id] = service.get_round(round_id)["state"]
                else:
                    service.refund_round(round_id, reason="deadline_expired")
                    outcomes[round_id] = STATE_REFUNDED
                continue

            if adapter:
                await _invoke(adapter.restore, round_record, service)
                outcomes[round_id] = "restored"
            else:
                service.refund_round(round_id, reason="missing_recovery_adapter")
                outcomes[round_id] = STATE_REFUNDED
        except Exception as exc:
            logger.exception(f"付费回合恢复失败 round_id={round_id}: {exc}")
            outcomes[round_id] = "error"

    return outcomes


async def _recovery_loop() -> None:
    while True:
        try:
            await recover_unfinished_rounds()
        except Exception as exc:
            logger.exception(f"付费回合周期恢复失败: {exc}")
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)


def install_recovery_hooks(driver) -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    async def startup() -> None:
        global _recovery_task
        await recover_unfinished_rounds()
        _recovery_task = asyncio.create_task(_recovery_loop())

    async def shutdown() -> None:
        global _recovery_task
        if _recovery_task is None:
            return
        _recovery_task.cancel()
        try:
            await _recovery_task
        except asyncio.CancelledError:
            pass
        _recovery_task = None

    driver.on_startup(startup)
    driver.on_shutdown(shutdown)
