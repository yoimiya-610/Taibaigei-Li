from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common.accounting import (
    ASSET_POINTS,
    STATUS_PENDING,
    credit_balance,
    get_balance,
    get_transaction_status,
    settle_transaction,
)
from mybot.common.paid_rounds import (
    PARTICIPANT_ACTIVE,
    PARTICIPANT_SETTLED,
    STATE_ACTIVE,
    STATE_EXPIRED,
    STATE_REFUNDED,
    STATE_SETTLED,
    PaidRoundService,
    recover_unfinished_rounds,
    register_recovery_adapter,
)


class PaidRoundRecoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        base = Path(self.tmp_dir.name)
        self.points_path = base / "points.json"
        self.rounds_path = base / "paid_rounds.json"
        self.service = PaidRoundService(
            self.rounds_path,
            ledger_paths={ASSET_POINTS: self.points_path},
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _credit(self, user_id: str, amount: int = 100) -> None:
        credit_balance(
            f"seed:{user_id}",
            ASSET_POINTS,
            user_id,
            "g1",
            amount,
            "test_seed",
            store_path=self.points_path,
        )

    def _create_round(
        self,
        round_id: str,
        *,
        game_type: str,
        user_id: str = "u1",
        amount: int = 40,
        result: dict | None = None,
        payout: int = 0,
        deadline_at: float | None = None,
        feature_key: str | None = None,
    ) -> dict:
        return self.service.create_round(
            round_id=round_id,
            game_type=game_type,
            mode="test",
            group_id="g1",
            creator_id=user_id,
            asset_type=ASSET_POINTS,
            feature_key=feature_key,
            payload={"hidden": [1, 2, 3], "seed": 42},
            result=result,
            participants=[
                {
                    "user_id": user_id,
                    "amount": amount,
                    "payout_amount": payout,
                }
            ],
            deadline_at=deadline_at,
        )

    async def test_missing_round_file_starts_empty(self):
        self.assertFalse(self.rounds_path.exists())
        self.assertEqual(self.service.list_rounds(unfinished_only=True), [])

        outcomes = await recover_unfinished_rounds(self.service)

        self.assertEqual(outcomes, {})
        self.assertFalse(self.rounds_path.exists())

    async def test_exit_after_round_save_before_freeze_never_charges(self):
        self._credit("u1")
        self._create_round("r-before-freeze", game_type="test_before_freeze")

        outcomes = await recover_unfinished_rounds(self.service)

        self.assertEqual(outcomes["r-before-freeze"], STATE_EXPIRED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)
        self.assertIsNone(
            get_transaction_status(
                "round:r-before-freeze:stake:u1",
                ASSET_POINTS,
                store_path=self.points_path,
            )
        )

    async def test_exit_after_freeze_restores_original_payload_once(self):
        self._credit("u1")
        game_type = "test_personal_restore"
        loaded: dict[str, dict] = {}

        def restore(round_record, service):
            loaded[round_record["round_id"]] = round_record["payload"]

        register_recovery_adapter(
            game_type,
            restore=restore,
            is_loaded=lambda round_record: round_record["round_id"] in loaded,
            discard=lambda round_record, service: loaded.pop(round_record["round_id"], None),
        )
        self._create_round("r-restore", game_type=game_type)
        self.service.freeze_participant("r-restore", "u1")

        first = await recover_unfinished_rounds(self.service)
        second = await recover_unfinished_rounds(self.service)

        self.assertEqual(first["r-restore"], "restored")
        self.assertEqual(second["r-restore"], "loaded")
        self.assertEqual(loaded["r-restore"], {"hidden": [1, 2, 3], "seed": 42})
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 60)
        self.assertEqual(
            get_transaction_status(
                "round:r-restore:stake:u1",
                ASSET_POINTS,
                store_path=self.points_path,
            ),
            STATUS_PENDING,
        )

    async def test_settlement_retries_after_stake_settled_before_payout(self):
        self._credit("u1")
        self._create_round("r-stake-step", game_type="test_stake_step")
        self.service.freeze_participant("r-stake-step", "u1")
        self.service.prepare_settlement(
            "r-stake-step",
            result={"outcome": "win"},
            payouts={"u1": 70},
        )
        settle_transaction(
            "round:r-stake-step:stake:u1",
            ASSET_POINTS,
            store_path=self.points_path,
        )

        outcomes = await recover_unfinished_rounds(self.service)
        repeated = await recover_unfinished_rounds(self.service)

        self.assertEqual(outcomes["r-stake-step"], STATE_SETTLED)
        self.assertNotIn("r-stake-step", repeated)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 130)

    async def test_payout_success_before_round_close_is_not_duplicated(self):
        self._credit("u1")
        self._create_round("r-payout-step", game_type="test_payout_step")
        self.service.freeze_participant("r-payout-step", "u1")
        self.service.prepare_settlement(
            "r-payout-step",
            result={"outcome": "win"},
            payouts={"u1": 80},
        )
        first = self.service.settle_participant("r-payout-step", "u1")

        self.assertEqual(first["status"], PARTICIPANT_SETTLED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 140)

        await recover_unfinished_rounds(self.service)
        self.service.settle_round("r-payout-step")

        self.assertEqual(self.service.get_round("r-payout-step")["state"], STATE_SETTLED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 140)

    async def test_refund_recovery_is_idempotent(self):
        self._credit("u1")
        self._create_round("r-refund", game_type="test_refund")
        self.service.freeze_participant("r-refund", "u1")

        first = self.service.refund_round("r-refund", reason="unsafe_state")
        second = self.service.refund_round("r-refund", reason="unsafe_state")

        self.assertEqual(first["state"], STATE_REFUNDED)
        self.assertEqual(second["state"], STATE_REFUNDED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)

    async def test_multi_participant_partial_settlement_recovers_once(self):
        self._credit("u1")
        self._credit("u2")
        self._create_round("r-multi", game_type="test_multi")
        self.service.add_participant(
            "r-multi",
            participant_id="u2",
            user_id="u2",
            amount=30,
            metadata={"role": "bet"},
        )
        self.service.freeze_participant("r-multi", "u1")
        self.service.freeze_participant("r-multi", "u2")
        self.service.prepare_settlement(
            "r-multi",
            result={"winner": "u2"},
            payouts={"u1": 0, "u2": 90},
        )
        self.service.settle_participant("r-multi", "u1")

        await recover_unfinished_rounds(self.service)
        await recover_unfinished_rounds(self.service)

        self.assertEqual(self.service.get_round("r-multi")["state"], STATE_SETTLED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 60)
        self.assertEqual(get_balance(ASSET_POINTS, "u2", "g1", store_path=self.points_path), 160)

    async def test_deadline_restore_before_and_settle_after_expiry(self):
        self._credit("u1")
        game_type = "test_deadline"
        loaded: set[str] = set()

        def restore(round_record, service):
            loaded.add(round_record["round_id"])

        def discard(round_record, service):
            loaded.discard(round_record["round_id"])

        def on_due(round_record, service):
            service.prepare_settlement(
                round_record["round_id"],
                result={"seed": round_record["payload"]["seed"], "outcome": "done"},
                payouts={"u1": 50},
            )
            service.settle_round(round_record["round_id"])
            discard(round_record, service)

        register_recovery_adapter(
            game_type,
            restore=restore,
            is_loaded=lambda round_record: round_record["round_id"] in loaded,
            discard=discard,
            on_due=on_due,
        )
        self._create_round("r-deadline", game_type=game_type, deadline_at=200)
        self.service.freeze_participant("r-deadline", "u1")

        before = await recover_unfinished_rounds(self.service, now=199)
        after = await recover_unfinished_rounds(self.service, now=201)

        self.assertEqual(before["r-deadline"], "restored")
        self.assertEqual(after["r-deadline"], STATE_SETTLED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 110)

    async def test_feature_disabled_refunds_unknown_result_but_settles_known_result(self):
        self._credit("u1")
        self._credit("u2")
        self._create_round(
            "r-disabled-refund",
            game_type="test_disabled_refund",
            user_id="u1",
            feature_key="disabled_test",
        )
        self._create_round(
            "r-disabled-settle",
            game_type="test_disabled_settle",
            user_id="u2",
            feature_key="disabled_test",
            result={"outcome": "known"},
            payout=60,
        )
        self.service.freeze_participant("r-disabled-refund", "u1")
        self.service.freeze_participant("r-disabled-settle", "u2")

        with patch("mybot.common.feature_flags.is_feature_enabled", return_value=False):
            outcomes = await recover_unfinished_rounds(self.service)

        self.assertEqual(outcomes["r-disabled-refund"], STATE_REFUNDED)
        self.assertEqual(outcomes["r-disabled-settle"], STATE_SETTLED)
        self.assertEqual(get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_path), 100)
        self.assertEqual(get_balance(ASSET_POINTS, "u2", "g1", store_path=self.points_path), 120)

    async def test_reconcile_freeze_success_before_activation(self):
        self._credit("u1")
        game_type = "test_activation_window"
        restored: set[str] = set()
        register_recovery_adapter(
            game_type,
            restore=lambda round_record, service: restored.add(round_record["round_id"]),
            is_loaded=lambda round_record: round_record["round_id"] in restored,
            discard=lambda round_record, service: restored.discard(round_record["round_id"]),
        )
        round_record = self._create_round("r-activation", game_type=game_type)
        participant = round_record["participants"]["u1"]
        from mybot.common.accounting import freeze_balance

        freeze_balance(
            participant["stake_tx_id"],
            ASSET_POINTS,
            "u1",
            "g1",
            40,
            participant["business_type"],
            store_path=self.points_path,
        )

        await recover_unfinished_rounds(self.service)

        recovered = self.service.get_round("r-activation")
        self.assertEqual(recovered["state"], STATE_ACTIVE)
        self.assertEqual(recovered["participants"]["u1"]["state"], PARTICIPANT_ACTIVE)
        self.assertIn("r-activation", restored)


if __name__ == "__main__":
    unittest.main()
