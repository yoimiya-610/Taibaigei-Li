import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common.accounting import ASSET_POINTS, credit_balance, get_balance
from mybot.common.paid_rounds import PaidRoundService
from mybot.plugins_disabled import dice


class QQDiceSettlementTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        base = Path(self.tmp_dir.name)
        self.points_path = base / "points.json"
        self.service = PaidRoundService(
            base / "paid_rounds.json",
            ledger_paths={ASSET_POINTS: self.points_path},
        )
        dice.active_games.clear()
        dice.settlement_locks.clear()

    def tearDown(self):
        dice.active_games.clear()
        dice.settlement_locks.clear()
        self.tmp_dir.cleanup()

    def _create_big_bet_round(self) -> dict:
        credit_balance(
            "seed:u1",
            ASSET_POINTS,
            "u1",
            "100",
            100,
            "test_seed",
            store_path=self.points_path,
        )
        game = {
            "bets": {"u1": {"type": "大", "amount": 20, "nickname": "甲"}},
            "starter": "庄",
            "seed": 1,
            "round_id": "qq-dice-settlement",
        }
        self.service.create_round(
            round_id=game["round_id"],
            game_type=dice.GAME_TYPE,
            mode="timed",
            group_id="100",
            creator_id="owner",
            asset_type=ASSET_POINTS,
            payload=game,
            deadline_at=10,
        )
        self.service.add_participant(
            game["round_id"],
            participant_id="u1",
            user_id="u1",
            amount=20,
            metadata={"role": "bet", "type": "大", "nickname": "甲"},
        )
        self.service.freeze_participant(game["round_id"], "u1")
        dice.active_games["100"] = game
        return game

    def test_extracts_dice_result_from_onebot_message_shapes(self):
        message = Message([MessageSegment("dice", {"result": "5"})])

        self.assertEqual(dice._extract_dice_result(message), 5)
        self.assertEqual(
            dice._extract_dice_result(
                {"message": [{"type": "dice", "data": {"result": "4"}}]}
            ),
            4,
        )
        self.assertEqual(
            dice._extract_dice_result({"raw_message": "[CQ:dice,result=3]"}),
            3,
        )
        self.assertIsNone(
            dice._extract_dice_result(
                {"message": [{"type": "dice", "data": {"result": "7"}}]}
            )
        )

    async def test_native_qq_dice_results_drive_single_idempotent_settlement(self):
        game = self._create_big_bet_round()
        bot = SimpleNamespace(
            send_group_msg=AsyncMock(
                side_effect=[
                    {"message_id": "dice-1"},
                    {"message_id": "dice-2"},
                    {"message_id": "dice-3"},
                    {"message_id": "settlement"},
                ]
            ),
            get_msg=AsyncMock(
                side_effect=[
                    {"message": [{"type": "dice", "data": {"result": "6"}}]},
                    {"message": [{"type": "dice", "data": {"result": "4"}}]},
                    {"message": [{"type": "dice", "data": {"result": "1"}}]},
                ]
            ),
        )

        with patch.object(dice, "_round_service", return_value=self.service):
            await asyncio.gather(
                dice.settle_game(bot, "100"),
                dice.settle_game(bot, "100"),
            )

        stored = self.service.get_round(game["round_id"])
        self.assertEqual(
            stored["result"],
            {"dice": [6, 4, 1], "total": 11, "result": "大", "is_triple": False},
        )
        self.assertEqual(stored["state"], "settled")
        self.assertEqual(
            get_balance(ASSET_POINTS, "u1", "100", store_path=self.points_path),
            119,
        )
        self.assertNotIn("100", dice.active_games)
        self.assertEqual(bot.send_group_msg.await_count, 4)
        for call in bot.send_group_msg.await_args_list[:3]:
            segment = call.kwargs["message"]
            self.assertIsInstance(segment, MessageSegment)
            self.assertEqual(segment.type, "dice")
            self.assertEqual(segment.data, {})
        self.assertIn(
            "🎲 6 | 🎲 4 | 🎲 1",
            bot.send_group_msg.await_args_list[3].kwargs["message"],
        )

    async def test_retry_reuses_persisted_dice_message_instead_of_rerolling(self):
        game = {
            "bets": {},
            "starter": "庄",
            "round_id": "qq-dice-retry",
        }
        self.service.create_round(
            round_id=game["round_id"],
            game_type=dice.GAME_TYPE,
            mode="timed",
            group_id="100",
            creator_id="owner",
            asset_type=ASSET_POINTS,
            payload=game,
            deadline_at=10,
        )
        first_bot = SimpleNamespace(
            send_group_msg=AsyncMock(return_value={"message_id": "dice-1"}),
            get_msg=AsyncMock(return_value={"message": []}),
        )

        with patch.object(dice, "QQ_DICE_FETCH_DELAY_SECONDS", 0):
            with self.assertRaises(dice.QQDiceResultError):
                await dice._collect_qq_dice_results(first_bot, "100", game, self.service)

        self.assertEqual(first_bot.send_group_msg.await_count, 1)
        self.assertEqual(
            self.service.get_round(game["round_id"])["payload"]["qq_dice_rolls"],
            [{"message_id": "dice-1"}],
        )

        resumed_bot = SimpleNamespace(
            send_group_msg=AsyncMock(
                side_effect=[
                    {"message_id": "dice-2"},
                    {"message_id": "dice-3"},
                ]
            ),
            get_msg=AsyncMock(
                side_effect=[
                    {"message": [{"type": "dice", "data": {"result": "2"}}]},
                    {"message": [{"type": "dice", "data": {"result": "3"}}]},
                    {"message": [{"type": "dice", "data": {"result": "4"}}]},
                ]
            ),
        )

        results = await dice._collect_qq_dice_results(
            resumed_bot,
            "100",
            game,
            self.service,
        )

        self.assertEqual(results, [2, 3, 4])
        self.assertEqual(resumed_bot.send_group_msg.await_count, 2)
        self.assertEqual(
            resumed_bot.get_msg.await_args_list[0].kwargs["message_id"],
            "dice-1",
        )
        self.assertEqual(
            self.service.get_round(game["round_id"])["payload"]["qq_dice_rolls"],
            [
                {"message_id": "dice-1", "result": 2},
                {"message_id": "dice-2", "result": 3},
                {"message_id": "dice-3", "result": 4},
            ],
        )


if __name__ == "__main__":
    unittest.main()
