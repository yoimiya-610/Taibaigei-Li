from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mybot.common.json_store import load_json, mutate_json
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)

ASSET_POINTS = "points"
ASSET_WINE_MONEY = "wine_money"
SUPPORTED_ASSETS = (ASSET_POINTS, ASSET_WINE_MONEY)

STATUS_PENDING = "pending"
STATUS_SETTLED = "settled"
STATUS_REFUNDED = "refunded"
STATUS_CANCELLED = "cancelled"

ACCOUNTING_SCHEMA_VERSION = 1
ACCOUNTING_ROOT_KEY = "_accounting"
TRANSACTIONS_KEY = "transactions"

POINTS_FILE = Path(__file__).resolve().parent.parent / "data" / "points.json"
TAVERN_FILE = Path(__file__).resolve().parent.parent / "data" / "taibai_tavern.json"


class AccountingError(RuntimeError):
    """Base exception for rejected accounting operations."""


class InvalidAccountingRequest(AccountingError):
    """Raised when an accounting request is incomplete or invalid."""


class AccountingDataError(AccountingError):
    """Raised when an existing ledger has an unsafe or incompatible shape."""


class TransactionConflictError(AccountingError):
    """Raised when a transaction id is reused with different parameters."""


class TransactionNotFoundError(AccountingError):
    """Raised when a requested transaction does not exist."""


class InvalidTransactionStateError(AccountingError):
    """Raised when a transaction cannot make the requested state transition."""


@dataclass(frozen=True)
class _AssetConfig:
    default_data: dict
    balance_field: str


_ASSET_CONFIGS = {
    ASSET_POINTS: _AssetConfig({}, "current"),
    ASSET_WINE_MONEY: _AssetConfig({"accounts": {}}, "wine_money"),
}


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_identity(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise InvalidAccountingRequest(f"{field} must not be empty")
    return normalized


def _normalize_positive_amount(amount: int) -> int:
    if isinstance(amount, bool):
        raise InvalidAccountingRequest("amount must be a positive integer")
    try:
        normalized = int(amount)
    except (TypeError, ValueError) as exc:
        raise InvalidAccountingRequest("amount must be a positive integer") from exc
    if normalized <= 0:
        raise InvalidAccountingRequest("amount must be a positive integer")
    return normalized


def _normalize_integer(amount: int) -> int:
    if isinstance(amount, bool):
        raise InvalidAccountingRequest("amount must be an integer")
    try:
        return int(amount)
    except (TypeError, ValueError) as exc:
        raise InvalidAccountingRequest("amount must be an integer") from exc


def _new_compat_tx_id(operation: str) -> str:
    return f"compat:{operation}:{uuid4().hex}"


class AccountingService:
    """Atomic JSON accounting for one asset type.

    Each transaction is stored in the same JSON document as its balance. The
    json_store lock therefore protects both the balance mutation and the
    transaction state change as one authoritative update.
    """

    def __init__(self, asset_type: str, store_path: Path | str | None = None):
        if asset_type not in _ASSET_CONFIGS:
            raise InvalidAccountingRequest(f"unsupported asset_type: {asset_type}")
        self.asset_type = asset_type
        self._config = _ASSET_CONFIGS[asset_type]
        default_path = POINTS_FILE if asset_type == ASSET_POINTS else TAVERN_FILE
        self.store_path = Path(store_path) if store_path is not None else default_path

    @property
    def _default_data(self) -> dict:
        return copy.deepcopy(self._config.default_data)

    def _accounts(self, data: dict, *, create: bool) -> dict:
        if not isinstance(data, dict):
            raise AccountingDataError("ledger root must be an object")
        if self.asset_type == ASSET_POINTS:
            return data

        accounts = data.get("accounts")
        if accounts is None and create:
            accounts = {}
            data["accounts"] = accounts
        if accounts is None:
            return {}
        if not isinstance(accounts, dict):
            raise AccountingDataError("ledger accounts must be an object")
        return accounts

    @staticmethod
    def _account_key(user_id: str, group_id: str) -> str:
        return f"{group_id}_{user_id}"

    def _new_account(self, user_id: str, group_id: str) -> dict:
        record = {"user_id": user_id, "group_id": group_id, self._config.balance_field: 0}
        if self.asset_type == ASSET_POINTS:
            record["total"] = 0
        return record

    def _account(self, data: dict, user_id: str, group_id: str, *, create: bool) -> dict | None:
        accounts = self._accounts(data, create=create)
        key = self._account_key(user_id, group_id)
        record = accounts.get(key)
        if record is None and create:
            record = self._new_account(user_id, group_id)
            accounts[key] = record
        if record is not None and not isinstance(record, dict):
            raise AccountingDataError(f"account record must be an object: {key}")
        return record

    def _balance(self, record: dict | None) -> int:
        if record is None:
            return 0
        value = record.get(self._config.balance_field, 0)
        try:
            balance = int(value)
        except (TypeError, ValueError) as exc:
            raise AccountingDataError("account balance must be an integer") from exc
        if self.asset_type == ASSET_WINE_MONEY:
            return max(balance, 0)
        return balance

    def _set_balance(self, record: dict, balance: int) -> None:
        record[self._config.balance_field] = balance

    @staticmethod
    def _points_total(record: dict) -> int:
        try:
            return int(record.get("total", 0))
        except (TypeError, ValueError) as exc:
            raise AccountingDataError("points total must be an integer") from exc

    @staticmethod
    def _transaction_store(data: dict, *, create: bool) -> dict:
        accounting = data.get(ACCOUNTING_ROOT_KEY)
        if accounting is None and create:
            accounting = {"version": ACCOUNTING_SCHEMA_VERSION, TRANSACTIONS_KEY: {}}
            data[ACCOUNTING_ROOT_KEY] = accounting
        if accounting is None:
            return {}
        if not isinstance(accounting, dict):
            raise AccountingDataError("accounting metadata must be an object")

        transactions = accounting.get(TRANSACTIONS_KEY)
        if transactions is None and create:
            transactions = {}
            accounting[TRANSACTIONS_KEY] = transactions
            accounting.setdefault("version", ACCOUNTING_SCHEMA_VERSION)
        if transactions is None:
            return {}
        if not isinstance(transactions, dict):
            raise AccountingDataError("accounting transactions must be an object")
        return transactions

    def _new_transaction(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
        operation: str,
        status: str,
        count_total_earned: bool = False,
        delta: int | None = None,
        asset_type: str | None = None,
    ) -> dict:
        if asset_type is not None and asset_type != self.asset_type:
            raise InvalidAccountingRequest(f"asset_type does not match service: {asset_type}")
        now = _now_text()
        transaction = {
            "version": ACCOUNTING_SCHEMA_VERSION,
            "tx_id": tx_id,
            "asset_type": self.asset_type,
            "group_id": group_id,
            "user_id": user_id,
            "amount": amount,
            "business_type": business_type,
            "operation": operation,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        if operation == "credit":
            transaction["count_total_earned"] = bool(count_total_earned)
        if delta is not None:
            transaction["delta"] = delta
        return transaction

    def _assert_same_request(self, transaction: dict, expected: dict[str, Any]) -> None:
        if not isinstance(transaction, dict):
            raise AccountingDataError("transaction record must be an object")
        mismatches = {
            field: (transaction.get(field), value)
            for field, value in expected.items()
            if transaction.get(field) != value
        }
        if not mismatches:
            return
        logger.warning(
            f"账务交易号参数冲突 tx_id={expected.get('tx_id')} "
            f"asset_type={self.asset_type} mismatches={mismatches}"
        )
        raise TransactionConflictError(f"transaction parameters conflict: {expected.get('tx_id')}")

    def _request(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
        operation: str,
        count_total_earned: bool | None = None,
    ) -> dict[str, Any]:
        request = {
            "tx_id": _normalize_identity(tx_id, "tx_id"),
            "asset_type": self.asset_type,
            "group_id": _normalize_identity(group_id, "group_id"),
            "user_id": _normalize_identity(user_id, "user_id"),
            "amount": _normalize_positive_amount(amount),
            "business_type": _normalize_identity(business_type, "business_type"),
            "operation": operation,
        }
        if count_total_earned is not None:
            request["count_total_earned"] = bool(count_total_earned)
        return request

    def _result(self, transaction: dict, record: dict, *, applied: bool, ok: bool = True) -> dict:
        return {
            "ok": ok,
            "applied": applied,
            "status": transaction["status"],
            "balance": self._balance(record),
            "transaction": copy.deepcopy(transaction),
            "record": copy.deepcopy(record),
        }

    def get_balance(self, user_id: str, group_id: str) -> int:
        user_id = _normalize_identity(user_id, "user_id")
        group_id = _normalize_identity(group_id, "group_id")
        data = load_json(self.store_path, self._default_data)
        return self._balance(self._account(data, user_id, group_id, create=False))

    def get_account(self, user_id: str, group_id: str, *, create: bool = False) -> dict:
        user_id = _normalize_identity(user_id, "user_id")
        group_id = _normalize_identity(group_id, "group_id")
        if not create:
            data = load_json(self.store_path, self._default_data)
            record = self._account(data, user_id, group_id, create=False)
            return copy.deepcopy(record or self._new_account(user_id, group_id))

        def mutator(data: dict) -> dict:
            return copy.deepcopy(self._account(data, user_id, group_id, create=True))

        return mutate_json(self.store_path, self._default_data, mutator)

    def credit(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
        count_total_earned: bool = True,
        legacy_idempotency_list: bool = False,
    ) -> dict:
        request = self._request(
            tx_id=tx_id,
            user_id=user_id,
            group_id=group_id,
            amount=amount,
            business_type=business_type,
            operation="credit",
            count_total_earned=count_total_earned,
        )

        def mutator(data: dict) -> dict:
            record = self._account(data, request["user_id"], request["group_id"], create=True)
            transactions = self._transaction_store(data, create=True)
            existing = transactions.get(request["tx_id"])
            if existing is not None:
                self._assert_same_request(existing, request)
                return self._result(existing, record, applied=False)

            if legacy_idempotency_list:
                legacy_ids = record.get("transactions", [])
                if legacy_ids is None:
                    legacy_ids = []
                if not isinstance(legacy_ids, list):
                    raise AccountingDataError("legacy transaction ids must be a list")
                if request["tx_id"] in legacy_ids:
                    return {
                        "ok": True,
                        "applied": False,
                        "status": STATUS_SETTLED,
                        "balance": self._balance(record),
                        "transaction": None,
                        "record": copy.deepcopy(record),
                    }

            self._set_balance(record, self._balance(record) + request["amount"])
            if self.asset_type == ASSET_POINTS and request["count_total_earned"]:
                record["total"] = self._points_total(record) + request["amount"]
            transaction = self._new_transaction(
                **request,
                status=STATUS_SETTLED,
            )
            transactions[request["tx_id"]] = transaction
            if legacy_idempotency_list:
                legacy_ids = record.setdefault("transactions", [])
                legacy_ids.append(request["tx_id"])
            return self._result(transaction, record, applied=True)

        return mutate_json(self.store_path, self._default_data, mutator)

    def debit(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
    ) -> dict:
        return self._debit_or_freeze(
            tx_id=tx_id,
            user_id=user_id,
            group_id=group_id,
            amount=amount,
            business_type=business_type,
            operation="debit",
            success_status=STATUS_SETTLED,
        )

    def freeze(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
    ) -> dict:
        return self._debit_or_freeze(
            tx_id=tx_id,
            user_id=user_id,
            group_id=group_id,
            amount=amount,
            business_type=business_type,
            operation="freeze",
            success_status=STATUS_PENDING,
        )

    def _debit_or_freeze(
        self,
        *,
        tx_id: str,
        user_id: str,
        group_id: str,
        amount: int,
        business_type: str,
        operation: str,
        success_status: str,
    ) -> dict:
        request = self._request(
            tx_id=tx_id,
            user_id=user_id,
            group_id=group_id,
            amount=amount,
            business_type=business_type,
            operation=operation,
        )

        def mutator(data: dict) -> dict:
            record = self._account(data, request["user_id"], request["group_id"], create=True)
            transactions = self._transaction_store(data, create=True)
            existing = transactions.get(request["tx_id"])
            if existing is not None:
                self._assert_same_request(existing, request)
                return self._result(
                    existing,
                    record,
                    applied=False,
                    ok=existing.get("status") != STATUS_CANCELLED,
                )

            balance = self._balance(record)
            enough = balance >= request["amount"]
            status = success_status if enough else STATUS_CANCELLED
            if enough:
                self._set_balance(record, balance - request["amount"])
            transaction = self._new_transaction(**request, status=status)
            transactions[request["tx_id"]] = transaction
            return self._result(transaction, record, applied=True, ok=enough)

        return mutate_json(self.store_path, self._default_data, mutator)

    def get_transaction(self, tx_id: str) -> dict | None:
        tx_id = _normalize_identity(tx_id, "tx_id")
        data = load_json(self.store_path, self._default_data)
        transaction = self._transaction_store(data, create=False).get(tx_id)
        if transaction is None:
            return None
        if not isinstance(transaction, dict):
            raise AccountingDataError("transaction record must be an object")
        return copy.deepcopy(transaction)

    def settle(self, tx_id: str, **expected: Any) -> dict:
        return self._transition(tx_id, STATUS_SETTLED, **expected)

    def refund(self, tx_id: str, **expected: Any) -> dict:
        return self._transition(tx_id, STATUS_REFUNDED, **expected)

    def cancel(self, tx_id: str, **expected: Any) -> dict:
        return self._transition(tx_id, STATUS_CANCELLED, **expected)

    def _transition(self, tx_id: str, target_status: str, **expected: Any) -> dict:
        tx_id = _normalize_identity(tx_id, "tx_id")
        allowed_expected = {"user_id", "group_id", "amount", "business_type"}
        unexpected = set(expected) - allowed_expected
        if unexpected:
            raise InvalidAccountingRequest(f"unexpected transaction fields: {sorted(unexpected)}")

        normalized_expected: dict[str, Any] = {"tx_id": tx_id, "asset_type": self.asset_type}
        for field, value in expected.items():
            if value is None:
                continue
            if field == "amount":
                normalized_expected[field] = _normalize_positive_amount(value)
            else:
                normalized_expected[field] = _normalize_identity(value, field)

        def mutator(data: dict) -> dict:
            transactions = self._transaction_store(data, create=False)
            transaction = transactions.get(tx_id)
            if transaction is None:
                raise TransactionNotFoundError(f"transaction not found: {tx_id}")
            self._assert_same_request(transaction, normalized_expected)
            if transaction.get("operation") != "freeze":
                raise InvalidTransactionStateError(f"transaction is not frozen: {tx_id}")

            user_id = _normalize_identity(transaction.get("user_id"), "user_id")
            group_id = _normalize_identity(transaction.get("group_id"), "group_id")
            record = self._account(data, user_id, group_id, create=True)
            current_status = transaction.get("status")
            if current_status == target_status:
                return self._result(transaction, record, applied=False)

            valid_sources = {
                STATUS_SETTLED: {STATUS_PENDING},
                STATUS_REFUNDED: {STATUS_PENDING},
                STATUS_CANCELLED: {STATUS_PENDING},
            }
            if current_status not in valid_sources[target_status]:
                raise InvalidTransactionStateError(
                    f"cannot transition transaction {tx_id} from {current_status} to {target_status}"
                )

            if target_status in {STATUS_REFUNDED, STATUS_CANCELLED}:
                self._set_balance(record, self._balance(record) + _normalize_positive_amount(transaction.get("amount")))
            transaction["status"] = target_status
            transaction["updated_at"] = _now_text()
            return self._result(transaction, record, applied=True)

        return mutate_json(self.store_path, self._default_data, mutator)

    def _legacy_adjust(
        self,
        *,
        delta: int,
        user_id: str,
        group_id: str,
        business_type: str,
        count_total_earned: bool,
    ) -> dict:
        delta = _normalize_integer(delta)
        user_id = _normalize_identity(user_id, "user_id")
        group_id = _normalize_identity(group_id, "group_id")
        if delta == 0:
            return self.get_account(user_id, group_id, create=True)
        tx_id = _new_compat_tx_id("adjust")

        def mutator(data: dict) -> dict:
            record = self._account(data, user_id, group_id, create=True)
            transactions = self._transaction_store(data, create=True)
            self._set_balance(record, self._balance(record) + delta)
            if self.asset_type == ASSET_POINTS and delta > 0 and count_total_earned:
                record["total"] = self._points_total(record) + delta
            transaction = self._new_transaction(
                tx_id=tx_id,
                user_id=user_id,
                group_id=group_id,
                amount=abs(delta),
                business_type=business_type,
                operation="adjustment",
                status=STATUS_SETTLED,
                count_total_earned=count_total_earned,
                delta=delta,
            )
            transactions[tx_id] = transaction
            return copy.deepcopy(record)

        return mutate_json(self.store_path, self._default_data, mutator)


def _service(asset_type: str, store_path: Path | str | None = None) -> AccountingService:
    return AccountingService(asset_type, store_path)


def get_balance(
    asset_type: str,
    user_id: str,
    group_id: str,
    *,
    store_path: Path | str | None = None,
) -> int:
    return _service(asset_type, store_path).get_balance(user_id, group_id)


def get_account_snapshot(
    asset_type: str,
    user_id: str,
    group_id: str,
    *,
    store_path: Path | str | None = None,
) -> dict:
    """Return one account without creating or rewriting an empty record."""

    return _service(asset_type, store_path).get_account(user_id, group_id, create=False)


def credit_balance(
    tx_id: str,
    asset_type: str,
    user_id: str,
    group_id: str,
    amount: int,
    business_type: str,
    *,
    count_total_earned: bool = True,
    store_path: Path | str | None = None,
) -> dict:
    return _service(asset_type, store_path).credit(
        tx_id=tx_id,
        user_id=user_id,
        group_id=group_id,
        amount=amount,
        business_type=business_type,
        count_total_earned=count_total_earned,
    )


def freeze_balance(
    tx_id: str,
    asset_type: str,
    user_id: str,
    group_id: str,
    amount: int,
    business_type: str,
    *,
    store_path: Path | str | None = None,
) -> dict:
    return _service(asset_type, store_path).freeze(
        tx_id=tx_id,
        user_id=user_id,
        group_id=group_id,
        amount=amount,
        business_type=business_type,
    )


def settle_transaction(
    tx_id: str,
    asset_type: str,
    *,
    store_path: Path | str | None = None,
    **expected: Any,
) -> dict:
    return _service(asset_type, store_path).settle(tx_id, **expected)


def refund_transaction(
    tx_id: str,
    asset_type: str,
    *,
    store_path: Path | str | None = None,
    **expected: Any,
) -> dict:
    return _service(asset_type, store_path).refund(tx_id, **expected)


def cancel_transaction(
    tx_id: str,
    asset_type: str,
    *,
    store_path: Path | str | None = None,
    **expected: Any,
) -> dict:
    return _service(asset_type, store_path).cancel(tx_id, **expected)


def get_transaction(
    tx_id: str,
    asset_type: str,
    *,
    store_path: Path | str | None = None,
) -> dict | None:
    return _service(asset_type, store_path).get_transaction(tx_id)


def get_transaction_status(
    tx_id: str,
    asset_type: str,
    *,
    store_path: Path | str | None = None,
) -> str | None:
    transaction = get_transaction(tx_id, asset_type, store_path=store_path)
    return transaction.get("status") if transaction is not None else None


# Compatibility adapters used by existing plugins. Calls without a caller-owned
# tx_id intentionally receive a fresh id so their historical non-idempotent
# behavior and return shapes remain unchanged.
def get_points(user_id: str, group_id: str, *, store_path: Path | str | None = None) -> dict:
    return _service(ASSET_POINTS, store_path).get_account(user_id, group_id, create=True)


def add_points(user_id: str, group_id: str, amount: int, *, store_path: Path | str | None = None) -> dict:
    service = _service(ASSET_POINTS, store_path)
    normalized = _normalize_integer(amount)
    if normalized <= 0:
        return service._legacy_adjust(
            delta=normalized,
            user_id=user_id,
            group_id=group_id,
            business_type="compat_add_points",
            count_total_earned=False,
        )
    return service.credit(
        tx_id=_new_compat_tx_id("add_points"),
        user_id=user_id,
        group_id=group_id,
        amount=normalized,
        business_type="compat_add_points",
        count_total_earned=True,
    )["record"]


def add_points_once(
    user_id: str,
    group_id: str,
    amount: int,
    tx_id: str,
    *,
    store_path: Path | str | None = None,
) -> dict:
    result = _service(ASSET_POINTS, store_path).credit(
        tx_id=tx_id,
        user_id=user_id,
        group_id=group_id,
        amount=amount,
        business_type="compat_add_points_once",
        count_total_earned=True,
        legacy_idempotency_list=True,
    )
    return {"applied": result["applied"], "record": result["record"]}


def spend_points(user_id: str, group_id: str, amount: int, *, store_path: Path | str | None = None) -> bool:
    try:
        normalized = _normalize_positive_amount(amount)
    except InvalidAccountingRequest:
        return False
    result = _service(ASSET_POINTS, store_path).debit(
        tx_id=_new_compat_tx_id("spend_points"),
        user_id=user_id,
        group_id=group_id,
        amount=normalized,
        business_type="compat_spend_points",
    )
    return bool(result["ok"])


def refund_points(user_id: str, group_id: str, amount: int, *, store_path: Path | str | None = None) -> dict:
    service = _service(ASSET_POINTS, store_path)
    normalized = _normalize_integer(amount)
    if normalized <= 0:
        return service._legacy_adjust(
            delta=normalized,
            user_id=user_id,
            group_id=group_id,
            business_type="compat_refund_points",
            count_total_earned=False,
        )
    return service.credit(
        tx_id=_new_compat_tx_id("refund_points"),
        user_id=user_id,
        group_id=group_id,
        amount=normalized,
        business_type="compat_refund_points",
        count_total_earned=False,
    )["record"]


def get_wine_money(user_id: str, group_id: str, *, store_path: Path | str | None = None) -> int:
    return _service(ASSET_WINE_MONEY, store_path).get_balance(user_id, group_id)


def add_wine_money(user_id: str, group_id: str, amount: int, *, store_path: Path | str | None = None) -> dict:
    service = _service(ASSET_WINE_MONEY, store_path)
    normalized = _normalize_integer(amount)
    if normalized <= 0:
        return service._legacy_adjust(
            delta=normalized,
            user_id=user_id,
            group_id=group_id,
            business_type="compat_add_wine_money",
            count_total_earned=False,
        )
    return service.credit(
        tx_id=_new_compat_tx_id("add_wine_money"),
        user_id=user_id,
        group_id=group_id,
        amount=normalized,
        business_type="compat_add_wine_money",
        count_total_earned=False,
    )["record"]


def spend_wine_money(
    user_id: str,
    group_id: str,
    amount: int,
    *,
    store_path: Path | str | None = None,
) -> dict:
    try:
        normalized = _normalize_positive_amount(amount)
    except InvalidAccountingRequest:
        return {"ok": False, "balance": get_wine_money(user_id, group_id, store_path=store_path)}
    result = _service(ASSET_WINE_MONEY, store_path).debit(
        tx_id=_new_compat_tx_id("spend_wine_money"),
        user_id=user_id,
        group_id=group_id,
        amount=normalized,
        business_type="compat_spend_wine_money",
    )
    return {"ok": result["ok"], "balance": result["balance"], "record": result["record"]}
