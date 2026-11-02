import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from nonebot.matcher import current_event, current_matcher

from mybot.common.accounting import (
    ASSET_POINTS,
    STATUS_PENDING,
    STATUS_SETTLED,
    credit_balance,
    get_balance,
    get_transaction_status,
)
from mybot.common.paid_rounds import PaidRoundService, recover_unfinished_rounds
from mybot.common.ai_client import _consume_current_ai_quota
from mybot.common.usage_policy import (
    OPERATION_AWAITING_CONFIRMATION,
    OPERATION_COMPLETED,
    OPERATION_PROCESSING,
    OPERATION_REFUNDED,
    PaidOperationExpired,
    PaidOperationInsufficientBalance,
    PaidOperationService,
    QuotaPlan,
    QuotaScope,
    WindowQuota,
    UsageQuotaExceeded,
    _loaded_paid_operations,
    clear_quota_records,
    consume_quota,
)


class UsageQuotaTest(unittest.TestCase):
    def setUp(self):
        clear_quota_records()

    def tearDown(self):
        clear_quota_records()

    def test_user_group_and_feature_quotas_are_atomic(self):
        plan = QuotaPlan(
            user=WindowQuota(2, 60),
            group=WindowQuota(3, 60),
            feature=WindowQuota(4, 60),
        )

        first = consume_quota("feature_a", "u1", "g1", plan, now=0)
        second = consume_quota("feature_a", "u1", "g1", plan, now=1)
        blocked_user = consume_quota("feature_a", "u1", "g1", plan, now=2)
        third = consume_quota("feature_a", "u2", "g1", plan, now=3)
        blocked_group = consume_quota("feature_a", "u3", "g1", plan, now=4)
        fourth = consume_quota("feature_a", "u1", "g2", plan, now=5)
        blocked_feature = consume_quota("feature_a", "u2", "g2", plan, now=6)

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(blocked_user.blocked_scope, QuotaScope.USER)
        self.assertTrue(third.allowed)
        self.assertEqual(blocked_group.blocked_scope, QuotaScope.GROUP)
        self.assertTrue(fourth.allowed)
        self.assertEqual(blocked_feature.blocked_scope, QuotaScope.FEATURE)

    def test_denied_attempt_does_not_consume_other_scopes(self):
        plan = QuotaPlan(
            user=WindowQuota(1, 60),
            group=WindowQuota(2, 60),
            feature=WindowQuota(3, 60),
        )
        self.assertTrue(consume_quota("feature_b", "u1", "g1", plan, now=0).allowed)
        self.assertFalse(consume_quota("feature_b", "u1", "g1", plan, now=1).allowed)
        allowed = consume_quota("feature_b", "u2", "g1", plan, now=2)
        self.assertTrue(allowed.allowed)
        self.assertEqual((allowed.remaining or {})[QuotaScope.GROUP], 0)

    def test_ai_client_uses_current_matcher_identity(self):
        event = SimpleNamespace(group_id=20001, get_user_id=lambda: "10001")
        matcher = SimpleNamespace(module_name="mybot.plugins.poem")
        event_token = current_event.set(event)
        matcher_token = current_matcher.set(matcher)
        try:
            decisions = [_consume_current_ai_quota() for _ in range(7)]
        finally:
            current_matcher.reset(matcher_token)
            current_event.reset(event_token)

        self.assertTrue(all(decision and decision.allowed for decision in decisions[:6]))
        self.assertIsNotNone(decisions[6])
        self.assertFalse(decisions[6].allowed)


class PaidOperationPolicyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        root = Path(self.tmp_dir.name)
        self.points_path = root / "points.json"
        self.rounds_path = root / "paid_rounds.json"
        self.round_service = PaidRoundService(
            self.rounds_path,
            ledger_paths={ASSET_POINTS: self.points_path},
        )
        self.service = PaidOperationService(self.round_service)
        credit_balance(
            "seed:u1",
            ASSET_POINTS,
            "u1",
            "g1",
            100,
            "test_seed",
            store_path=self.points_path,
        )
        _loaded_paid_operations.clear()

    def tearDown(self):
        _loaded_paid_operations.clear()
        self.tmp_dir.cleanup()

    def _begin(self, **overrides):
        values = {
            "feature_key": "paid_test",
            "user_id": "u1",
            "group_id": "g1",
            "cost": 40,
            "request_key": "same request",
        }
        values.update(overrides)
        return self.service.begin(**values)

    async def test_processing_operation_is_frozen_once_and_duplicate_is_visible(self):
        first = self._begin()
        repeated = self._begin()

        self.assertEqual(first.status, OPERATION_PROCESSING)
        self.assertEqual(repeated.operation_id, first.operation_id)
        self.assertTrue(repeated.existing)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 60)
        self.assertEqual(
            get_transaction_status(
                f"round:{first.operation_id}:stake:u1",
                ASSET_POINTS,
                store_path=self.points_path,
            ),
            STATUS_PENDING,
        )

    async def test_completed_result_is_durable_and_settled(self):
        started = self._begin()
        completed = self.service.complete(started.operation_id, result_key="reply digest")

        self.assertEqual(completed.status, OPERATION_COMPLETED)
        self.assertEqual(
            get_transaction_status(
                f"round:{started.operation_id}:stake:u1",
                ASSET_POINTS,
                store_path=self.points_path,
            ),
            STATUS_SETTLED,
        )
        self.assertTrue(completed.record["result"]["completed"])
        self.assertNotIn("reply digest", str(completed.record))
        self.assertNotIn("same request", str(completed.record))

    async def test_restart_refunds_processing_without_a_recorded_result(self):
        started = self._begin()
        _loaded_paid_operations.clear()

        outcomes = await recover_unfinished_rounds(self.round_service)
        recovered = self.service.get(started.operation_id)

        self.assertEqual(outcomes[started.operation_id], "restored")
        self.assertEqual(recovered.status, OPERATION_REFUNDED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)

    async def test_restart_finishes_a_recorded_result(self):
        started = self._begin()
        self.service.record_result(started.operation_id, result_key="reply digest")
        _loaded_paid_operations.clear()

        outcomes = await recover_unfinished_rounds(self.round_service)

        self.assertEqual(outcomes[started.operation_id], "settled")
        self.assertEqual(self.service.get(started.operation_id).status, OPERATION_COMPLETED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 60)

    async def test_confirmation_survives_restart_without_early_charge(self):
        prepared = self._begin(confirmation_required=True, ttl_seconds=60)
        self.assertEqual(prepared.status, OPERATION_AWAITING_CONFIRMATION)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)
        _loaded_paid_operations.clear()

        await recover_unfinished_rounds(self.round_service)
        pending = self.service.find_open(
            feature_key="paid_test",
            user_id="u1",
            group_id="g1",
            request_key="same request",
        )
        confirmed = self.service.confirm(prepared.operation_id)

        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, OPERATION_AWAITING_CONFIRMATION)
        self.assertEqual(confirmed.status, OPERATION_PROCESSING)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 60)

    async def test_quota_denial_happens_before_operation_and_charge(self):
        plan = QuotaPlan(user=WindowQuota(1, 60))
        self.assertTrue(consume_quota("paid_test", "u1", "g1", plan, now=0).allowed)

        with self.assertRaises(UsageQuotaExceeded):
            self._begin(quota_plan=plan, now=1)

        self.assertEqual(self.round_service.list_rounds(), [])
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)

    async def test_insufficient_balance_leaves_no_open_operation(self):
        with self.assertRaises(PaidOperationInsufficientBalance):
            self._begin(cost=200)

        self.assertEqual(self.round_service.list_rounds(unfinished_only=True), [])
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)

    async def test_expired_confirmation_never_charges(self):
        prepared = self._begin(confirmation_required=True, ttl_seconds=10, now=100)

        with self.assertRaises(PaidOperationExpired):
            self.service.confirm(prepared.operation_id, now=111)

        self.assertEqual(self.service.get(prepared.operation_id).status, OPERATION_REFUNDED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)


if __name__ == "__main__":
    unittest.main()
