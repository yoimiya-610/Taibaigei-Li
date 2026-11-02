from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common.accounting import ASSET_WINE_MONEY, credit_balance, get_balance
from mybot.common.paid_rounds import PaidRoundService
from mybot.plugins import taibai_tavern


class TavernRpsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        base = Path(self.tmp_dir.name)
        self.wine_path = base / "taibai_tavern.json"
        self.service = PaidRoundService(
            base / "paid_rounds.json",
            ledger_paths={ASSET_WINE_MONEY: self.wine_path},
        )
        self.old_tavern_file = taibai_tavern.DATA_FILE
        taibai_tavern.DATA_FILE = self.wine_path
        taibai_tavern.pending_rps_challenges.clear()
        taibai_tavern.active_rps_duels.clear()
        taibai_tavern.rps_duel_locks.clear()

    def tearDown(self):
        taibai_tavern.DATA_FILE = self.old_tavern_file
        taibai_tavern.pending_rps_challenges.clear()
        taibai_tavern.active_rps_duels.clear()
        taibai_tavern.rps_duel_locks.clear()
        self.tmp_dir.cleanup()

    def _seed_wine(self, user_id: str, amount: int) -> None:
        credit_balance(
            f"seed:{user_id}",
            ASSET_WINE_MONEY,
            user_id,
            "100",
            amount,
            "test_seed",
            store_path=self.wine_path,
        )

    @staticmethod
    def _challenge(stake_wine: int = 20) -> dict:
        return {
            "challenge_id": "challenge-1",
            "group_id": "100",
            "challenger_id": "u1",
            "challenger_nickname": "青莲",
            "target_id": "u2",
            "target_nickname": "明月",
            "stake_wine": stake_wine,
            "created_at": 1.0,
            "expires_at": 61.0,
        }

    def _create_funded_round(self, stake_wine: int = 20) -> dict:
        self._seed_wine("u1", 100)
        self._seed_wine("u2", 100)
        result = taibai_tavern.create_rps_duel_round(
            self._challenge(stake_wine),
            service=self.service,
            now=10.0,
        )
        self.assertEqual(result["status"], "ok")
        return result["game"]

    def test_parses_onebot_at_target_and_wine_stake(self):
        args = Message(
            [
                MessageSegment.at("20002"),
                MessageSegment.text(" 20 酒钱"),
            ]
        )

        self.assertEqual(
            taibai_tavern.parse_rps_challenge_args(args),
            {"target_id": "20002", "stake_wine": 20},
        )
        self.assertIsNone(
            taibai_tavern.parse_rps_challenge_args(
                Message([MessageSegment.text("@同名群友 20")])
            )
        )
        self.assertIsNone(
            taibai_tavern.parse_rps_challenge_args(
                Message([MessageSegment.at("all"), MessageSegment.text("20")])
            )
        )

    def test_rps_mapping_matches_napcat_result_contract(self):
        self.assertEqual(taibai_tavern.compare_rps(1, 2), 1)
        self.assertEqual(taibai_tavern.compare_rps(2, 3), 1)
        self.assertEqual(taibai_tavern.compare_rps(3, 1), 1)
        self.assertEqual(taibai_tavern.compare_rps(1, 1), 0)
        self.assertEqual(taibai_tavern.compare_rps(2, 1), -1)

    def test_extracts_rps_result_from_onebot_message_shapes(self):
        message = Message([MessageSegment("rps", {"result": "2"})])

        self.assertEqual(taibai_tavern._extract_rps_result(message), 2)
        self.assertEqual(
            taibai_tavern._extract_rps_result(
                {"message": [{"type": "rps", "data": {"result": "3"}}]}
            ),
            3,
        )
        self.assertEqual(
            taibai_tavern._extract_rps_result({"raw_message": "[CQ:rps,result=1]"}),
            1,
        )
        self.assertIsNone(
            taibai_tavern._extract_rps_result(
                {"message": [{"type": "rps", "data": {"result": "4"}}]}
            )
        )

    async def test_native_qq_rps_settles_zero_sum_duel_once(self):
        game = self._create_funded_round()
        bot = SimpleNamespace(
            send_group_msg=AsyncMock(
                side_effect=[
                    {"message_id": "intro"},
                    {"message_id": "rps-1"},
                    {"message_id": "rps-2"},
                    {"message_id": "settlement"},
                ]
            ),
            get_msg=AsyncMock(
                side_effect=[
                    {"message": [{"type": "rps", "data": {"result": "1"}}]},
                    {"message": [{"type": "rps", "data": {"result": "2"}}]},
                ]
            ),
        )

        settled = await taibai_tavern._settle_rps_duel(
            bot,
            "100",
            service=self.service,
        )

        self.assertTrue(settled)
        stored = self.service.get_round(game["round_id"])
        self.assertEqual(stored["state"], "settled")
        self.assertEqual(stored["result"]["winner_id"], "u1")
        self.assertEqual(
            stored["result"]["rps"],
            [
                {"user_id": "u1", "result": 1},
                {"user_id": "u2", "result": 2},
            ],
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u1", "100", store_path=self.wine_path),
            120,
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u2", "100", store_path=self.wine_path),
            80,
        )
        self.assertNotIn("100", taibai_tavern.active_rps_duels)
        self.assertEqual(bot.send_group_msg.await_count, 4)
        for call in bot.send_group_msg.await_args_list[1:3]:
            segment = call.kwargs["message"]
            self.assertIsInstance(segment, MessageSegment)
            self.assertEqual(segment.type, "rps")
            self.assertEqual(segment.data, {})
        self.assertIn(
            "青莲：石头",
            bot.send_group_msg.await_args_list[3].kwargs["message"],
        )

    async def test_tie_returns_each_players_original_stake(self):
        game = self._create_funded_round()
        bot = SimpleNamespace(
            send_group_msg=AsyncMock(
                side_effect=[
                    {"message_id": "intro"},
                    {"message_id": "rps-1"},
                    {"message_id": "rps-2"},
                    {"message_id": "settlement"},
                ]
            ),
            get_msg=AsyncMock(
                side_effect=[
                    {"message": [{"type": "rps", "data": {"result": "3"}}]},
                    {"message": [{"type": "rps", "data": {"result": "3"}}]},
                ]
            ),
        )

        await taibai_tavern._settle_rps_duel(bot, "100", service=self.service)

        stored = self.service.get_round(game["round_id"])
        self.assertIsNone(stored["result"]["winner_id"])
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u1", "100", store_path=self.wine_path),
            100,
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u2", "100", store_path=self.wine_path),
            100,
        )

    def test_second_player_shortfall_refunds_first_player(self):
        self._seed_wine("u1", 100)
        self._seed_wine("u2", 10)

        result = taibai_tavern.create_rps_duel_round(
            self._challenge(),
            service=self.service,
            now=10.0,
        )

        self.assertEqual(result["status"], "target_insufficient_wine")
        self.assertEqual(
            self.service.get_round(result["game"]["round_id"])["state"],
            "refunded",
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u1", "100", store_path=self.wine_path),
            100,
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u2", "100", store_path=self.wine_path),
            10,
        )
        self.assertNotIn("100", taibai_tavern.active_rps_duels)

    async def test_retry_reuses_persisted_rps_message_instead_of_rethrowing(self):
        game = self._create_funded_round()
        first_bot = SimpleNamespace(
            send_group_msg=AsyncMock(
                side_effect=[
                    {"message_id": "intro"},
                    {"message_id": "rps-1"},
                ]
            ),
            get_msg=AsyncMock(return_value={"message": []}),
        )

        with patch.object(taibai_tavern, "RPS_FETCH_DELAY_SECONDS", 0):
            with self.assertRaises(taibai_tavern.QQRpsResultError):
                await taibai_tavern._collect_qq_rps_results(
                    first_bot,
                    "100",
                    game,
                    self.service,
                )

        self.assertEqual(
            self.service.get_round(game["round_id"])["payload"]["qq_rps_rolls"],
            [{"participant_id": "u1", "message_id": "rps-1"}],
        )

        resumed_bot = SimpleNamespace(
            send_group_msg=AsyncMock(return_value={"message_id": "rps-2"}),
            get_msg=AsyncMock(
                side_effect=[
                    {"message": [{"type": "rps", "data": {"result": "2"}}]},
                    {"message": [{"type": "rps", "data": {"result": "3"}}]},
                ]
            ),
        )

        results = await taibai_tavern._collect_qq_rps_results(
            resumed_bot,
            "100",
            game,
            self.service,
        )

        self.assertEqual(results, {"u1": 2, "u2": 3})
        self.assertEqual(resumed_bot.send_group_msg.await_count, 1)
        self.assertEqual(
            resumed_bot.get_msg.await_args_list[0].kwargs["message_id"],
            "rps-1",
        )
        self.assertEqual(
            self.service.get_round(game["round_id"])["payload"]["qq_rps_rolls"],
            [
                {"participant_id": "u1", "message_id": "rps-1", "result": 2},
                {"participant_id": "u2", "message_id": "rps-2", "result": 3},
            ],
        )

    async def test_result_timeout_refunds_both_frozen_stakes(self):
        game = self._create_funded_round()
        round_record = self.service.get_round(game["round_id"])

        with patch.object(taibai_tavern, "_connected_bot", return_value=None):
            await taibai_tavern._settle_due_rps_round(round_record, self.service)

        self.assertEqual(self.service.get_round(game["round_id"])["state"], "refunded")
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u1", "100", store_path=self.wine_path),
            100,
        )
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u2", "100", store_path=self.wine_path),
            100,
        )
        self.assertNotIn("100", taibai_tavern.active_rps_duels)


if __name__ == "__main__":
    unittest.main()
