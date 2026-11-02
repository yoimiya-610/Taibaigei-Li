import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mybot.common.accounting import (
    ACCOUNTING_ROOT_KEY,
    ASSET_POINTS,
    ASSET_WINE_MONEY,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REFUNDED,
    STATUS_SETTLED,
    AccountingService,
    InvalidTransactionStateError,
    TransactionConflictError,
    add_points_once,
)
from mybot.common.json_store import JsonStoreReadError


class AccountingServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        base = Path(self.tmp_dir.name)
        self.points_path = base / "points.json"
        self.wine_path = base / "taibai_tavern.json"
        self.points = AccountingService(ASSET_POINTS, self.points_path)
        self.wine = AccountingService(ASSET_WINE_MONEY, self.wine_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _credit_points(self, amount: int = 100, tx_id: str = "seed") -> dict:
        return self.points.credit(
            tx_id=tx_id,
            user_id="u1",
            group_id="g1",
            amount=amount,
            business_type="test_seed",
        )

    def test_credit_freeze_and_settle_are_idempotent(self):
        first_credit = self._credit_points()
        second_credit = self._credit_points()
        self.assertTrue(first_credit["applied"])
        self.assertFalse(second_credit["applied"])
        self.assertEqual(self.points.get_account("u1", "g1")["total"], 100)

        frozen = self.points.freeze(
            tx_id="paid:1",
            user_id="u1",
            group_id="g1",
            amount=30,
            business_type="paid_feature",
        )
        duplicate = self.points.freeze(
            tx_id="paid:1",
            user_id="u1",
            group_id="g1",
            amount=30,
            business_type="paid_feature",
        )
        settled = self.points.settle("paid:1")
        settled_again = self.points.settle("paid:1")

        self.assertEqual(frozen["status"], STATUS_PENDING)
        self.assertTrue(frozen["applied"])
        self.assertFalse(duplicate["applied"])
        self.assertEqual(duplicate["balance"], 70)
        self.assertEqual(settled["status"], STATUS_SETTLED)
        self.assertTrue(settled["applied"])
        self.assertFalse(settled_again["applied"])
        self.assertEqual(self.points.get_balance("u1", "g1"), 70)

    def test_insufficient_freeze_is_cancelled_and_stays_idempotent(self):
        self._credit_points(20)
        first = self.points.freeze(
            tx_id="paid:insufficient",
            user_id="u1",
            group_id="g1",
            amount=30,
            business_type="paid_feature",
        )
        self._credit_points(20, "later-credit")
        duplicate = self.points.freeze(
            tx_id="paid:insufficient",
            user_id="u1",
            group_id="g1",
            amount=30,
            business_type="paid_feature",
        )

        self.assertFalse(first["ok"])
        self.assertEqual(first["status"], STATUS_CANCELLED)
        self.assertFalse(duplicate["ok"])
        self.assertFalse(duplicate["applied"])
        self.assertEqual(self.points.get_balance("u1", "g1"), 40)

    def test_reusing_transaction_id_with_different_parameters_is_rejected(self):
        self._credit_points()
        self.points.freeze(
            tx_id="paid:conflict",
            user_id="u1",
            group_id="g1",
            amount=10,
            business_type="paid_feature",
        )

        with self.assertRaises(TransactionConflictError):
            self.points.freeze(
                tx_id="paid:conflict",
                user_id="u1",
                group_id="g1",
                amount=11,
                business_type="paid_feature",
            )
        with self.assertRaises(TransactionConflictError):
            self.points.freeze(
                tx_id="paid:conflict",
                user_id="u2",
                group_id="g1",
                amount=10,
                business_type="paid_feature",
            )

        self.assertEqual(self.points.get_balance("u1", "g1"), 90)
        self.assertEqual(self.points.get_balance("u2", "g1"), 0)

    def test_refund_restores_current_only_and_is_idempotent(self):
        self._credit_points()
        self.points.freeze(
            tx_id="paid:refund",
            user_id="u1",
            group_id="g1",
            amount=25,
            business_type="paid_feature",
        )

        refunded = self.points.refund("paid:refund")
        duplicate = self.points.refund("paid:refund")
        record = self.points.get_account("u1", "g1")

        self.assertEqual(refunded["status"], STATUS_REFUNDED)
        self.assertTrue(refunded["applied"])
        self.assertFalse(duplicate["applied"])
        self.assertEqual(record["current"], 100)
        self.assertEqual(record["total"], 100)
        with self.assertRaises(InvalidTransactionStateError):
            self.points.settle("paid:refund")

    def test_settled_transaction_cannot_be_refunded(self):
        self._credit_points()
        self.points.freeze(
            tx_id="paid:settled",
            user_id="u1",
            group_id="g1",
            amount=10,
            business_type="paid_feature",
        )
        self.points.settle("paid:settled")

        with self.assertRaises(InvalidTransactionStateError):
            self.points.refund("paid:settled")
        self.assertEqual(self.points.get_balance("u1", "g1"), 90)

    def test_concurrent_consumption_never_overdraws(self):
        self._credit_points(100)

        def freeze(index: int) -> dict:
            return self.points.freeze(
                tx_id=f"concurrent:{index}",
                user_id="u1",
                group_id="g1",
                amount=10,
                business_type="concurrency_test",
            )

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(freeze, range(20)))

        pending = [result for result in results if result["status"] == STATUS_PENDING]
        cancelled = [result for result in results if result["status"] == STATUS_CANCELLED]
        self.assertEqual(len(pending), 10)
        self.assertEqual(len(cancelled), 10)
        self.assertEqual(self.points.get_balance("u1", "g1"), 0)
        self.assertGreaterEqual(min(result["balance"] for result in results), 0)

    def test_legacy_points_data_and_unknown_fields_are_preserved(self):
        legacy = {
            "g1_u1": {
                "current": 50,
                "total": 120,
                "user_id": "u1",
                "group_id": "g1",
                "custom": {"keep": True},
            },
            "future_root": {"unknown": 1},
        }
        self.points_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        self.points.freeze(
            tx_id="legacy:freeze",
            user_id="u1",
            group_id="g1",
            amount=20,
            business_type="legacy_test",
        )
        stored = json.loads(self.points_path.read_text(encoding="utf-8"))

        self.assertEqual(stored["g1_u1"]["current"], 30)
        self.assertEqual(stored["g1_u1"]["total"], 120)
        self.assertEqual(stored["g1_u1"]["custom"], {"keep": True})
        self.assertEqual(stored["future_root"], {"unknown": 1})
        transaction = stored[ACCOUNTING_ROOT_KEY]["transactions"]["legacy:freeze"]
        self.assertEqual(transaction["asset_type"], ASSET_POINTS)
        self.assertEqual(transaction["group_id"], "g1")
        self.assertEqual(transaction["user_id"], "u1")
        self.assertEqual(transaction["amount"], 20)
        self.assertEqual(transaction["business_type"], "legacy_test")
        self.assertIn("created_at", transaction)
        self.assertIn("updated_at", transaction)

    def test_legacy_once_ids_remain_idempotent(self):
        legacy = {
            "g1_u1": {
                "current": 50,
                "total": 50,
                "user_id": "u1",
                "group_id": "g1",
                "transactions": ["fortune:old"],
            }
        }
        self.points_path.write_text(json.dumps(legacy), encoding="utf-8")

        result = add_points_once(
            "u1",
            "g1",
            50,
            "fortune:old",
            store_path=self.points_path,
        )

        self.assertFalse(result["applied"])
        self.assertEqual(result["record"]["current"], 50)
        self.assertEqual(result["record"]["total"], 50)

    def test_wine_money_uses_same_transaction_lifecycle(self):
        self.wine.credit(
            tx_id="wine:seed",
            user_id="u1",
            group_id="g1",
            amount=80,
            business_type="wine_reward",
            count_total_earned=False,
        )
        self.wine.freeze(
            tx_id="wine:stake",
            user_id="u1",
            group_id="g1",
            amount=30,
            business_type="wine_game",
        )
        self.wine.cancel("wine:stake")
        stored = json.loads(self.wine_path.read_text(encoding="utf-8"))

        self.assertEqual(self.wine.get_balance("u1", "g1"), 80)
        self.assertEqual(stored["accounts"]["g1_u1"]["wine_money"], 80)
        self.assertEqual(
            stored[ACCOUNTING_ROOT_KEY]["transactions"]["wine:stake"]["status"],
            STATUS_CANCELLED,
        )

    def test_existing_transaction_unknown_fields_survive_transition(self):
        self._credit_points()
        self.points.freeze(
            tx_id="paid:future",
            user_id="u1",
            group_id="g1",
            amount=10,
            business_type="paid_feature",
        )
        stored = json.loads(self.points_path.read_text(encoding="utf-8"))
        stored[ACCOUNTING_ROOT_KEY]["transactions"]["paid:future"]["future_field"] = {"keep": True}
        self.points_path.write_text(json.dumps(stored), encoding="utf-8")

        self.points.settle("paid:future")
        updated = json.loads(self.points_path.read_text(encoding="utf-8"))
        transaction = updated[ACCOUNTING_ROOT_KEY]["transactions"]["paid:future"]
        self.assertEqual(transaction["future_field"], {"keep": True})
        self.assertEqual(transaction["status"], STATUS_SETTLED)

    def test_invalid_json_is_never_overwritten(self):
        original = '{"broken":'
        self.points_path.write_text(original, encoding="utf-8")

        with self.assertRaises(JsonStoreReadError):
            self.points.freeze(
                tx_id="broken:freeze",
                user_id="u1",
                group_id="g1",
                amount=10,
                business_type="safety_test",
            )

        self.assertEqual(self.points_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
