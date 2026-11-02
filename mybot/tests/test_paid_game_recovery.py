from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from mybot.common.accounting import ASSET_POINTS, ASSET_WINE_MONEY, credit_balance, get_balance
from mybot.common.paid_rounds import PaidRoundService
from mybot.plugins import taibai_tavern
from mybot.plugins_disabled import blackjack, dice, race, roulette, scratch


class PaidGameRecoveryAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        base = Path(self.tmp_dir.name)
        self.points_path = base / "points.json"
        self.wine_path = base / "taibai_tavern.json"
        self.rounds_path = base / "paid_rounds.json"
        self.service = PaidRoundService(
            self.rounds_path,
            ledger_paths={
                ASSET_POINTS: self.points_path,
                ASSET_WINE_MONEY: self.wine_path,
            },
        )
        blackjack.active_games.clear()
        scratch.active_games.clear()
        dice.active_games.clear()
        race.active_races.clear()
        roulette.pvp_games.clear()
        taibai_tavern.active_games.clear()
        taibai_tavern.active_ink_traces.clear()

    def tearDown(self):
        blackjack.active_games.clear()
        scratch.active_games.clear()
        dice.active_games.clear()
        race.active_races.clear()
        roulette.pvp_games.clear()
        taibai_tavern.active_games.clear()
        taibai_tavern.active_ink_traces.clear()
        self.tmp_dir.cleanup()

    def _credit(
        self,
        asset_type: str,
        user_id: str,
        amount: int = 100,
        group_id: str = "g1",
    ) -> None:
        store_path = self.points_path if asset_type == ASSET_POINTS else self.wine_path
        credit_balance(
            f"seed:{asset_type}:{user_id}",
            asset_type,
            user_id,
            group_id,
            amount,
            "test_seed",
            store_path=store_path,
        )

    async def test_personal_games_restore_exact_hidden_state(self):
        cases = (
            (
                "adapter-blackjack",
                blackjack.GAME_TYPE,
                {
                    "cards": [["A", "♠"], ["9", "♥"]],
                    "dealer": [["K", "♣"], ["7", "♦"]],
                    "deck": [["2", "♠"]],
                    "bet": 20,
                    "nickname": "甲",
                    "group_id": "g1",
                    "user_id": "u1",
                },
                blackjack._restore_round,
                blackjack.active_games,
            ),
            (
                "adapter-scratch",
                scratch.GAME_TYPE,
                {
                    "deck": [{"name": "月魄", "display": "🌙"}] * 9,
                    "bet": 20,
                    "level": 1,
                    "nickname": "甲",
                    "group_id": "g1",
                    "user_id": "u1",
                },
                scratch._restore_round,
                scratch.active_games,
            ),
            (
                "adapter-flip",
                taibai_tavern.FLIP_GAME_TYPE,
                {
                    "deck": ["吉", "凶", "吉", "吉", "凶"],
                    "revealed": [0],
                    "good_count": 1,
                    "bad_count": 2,
                    "mode": "random",
                    "stake_wine": 20,
                    "user_id": "u1",
                    "group_id": "g1",
                    "nickname": "甲",
                },
                taibai_tavern._restore_flip_round,
                taibai_tavern.active_games,
            ),
        )

        for round_id, game_type, payload, restore, active_store in cases:
            with self.subTest(game_type=game_type):
                record = self.service.create_round(
                    round_id=round_id,
                    game_type=game_type,
                    mode="personal",
                    group_id="g1",
                    creator_id="u1",
                    asset_type=ASSET_POINTS,
                    payload=payload,
                )
                restore(record, self.service)
                restored = active_store["g1_u1"]
                self.assertEqual(restored["deck"], payload["deck"])
                self.assertEqual(restored["round_id"], round_id)

    async def test_dice_recovers_frozen_bet_missing_from_room_snapshot(self):
        self._credit(ASSET_POINTS, "u1", group_id="100")
        record = self.service.create_round(
            round_id="adapter-dice",
            game_type=dice.GAME_TYPE,
            mode="timed",
            group_id="100",
            creator_id="owner",
            asset_type=ASSET_POINTS,
            payload={"bets": {}, "starter": "庄", "seed": 123, "round_id": "adapter-dice"},
            deadline_at=10,
        )
        self.service.add_participant(
            "adapter-dice",
            participant_id="u1",
            user_id="u1",
            amount=20,
            metadata={"role": "bet", "type": "大", "nickname": "甲"},
        )
        self.service.freeze_participant("adapter-dice", "u1")
        record = self.service.get_round("adapter-dice")

        dice._restore_round(record, self.service)

        self.assertEqual(
            dice.active_games["100"]["bets"]["u1"],
            {"type": "大", "amount": 20, "nickname": "甲"},
        )
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
            await dice.settle_game(bot, "100")
        self.assertEqual(self.service.get_round("adapter-dice")["state"], "settled")

    async def test_race_seed_replays_identical_winner(self):
        race_state = {
            "horses": race.HORSES[:4],
            "players": {},
            "started": False,
            "seed": 987654321,
        }

        first = race._simulate_race(race_state)
        second = race._simulate_race(race_state)

        self.assertEqual(first["positions"], second["positions"])
        self.assertEqual(first["finish_times"], second["finish_times"])
        self.assertEqual(first["results"], second["results"])
        self.assertEqual(first["winner_idx"], second["winner_idx"])
        self.assertEqual(first["frames"], second["frames"])

    async def test_multiplayer_round_recovers_participant_added_after_snapshot(self):
        self._credit(ASSET_POINTS, "u1")
        self.service.create_round(
            round_id="adapter-pvp",
            game_type=roulette.PVP_GAME_TYPE,
            mode="multiplayer",
            group_id="g1",
            creator_id="owner",
            asset_type=ASSET_POINTS,
            payload={
                "players": [],
                "bet": 20,
                "current": 0,
                "bullet": 4,
                "chamber": 0,
                "started": False,
                "round_id": "adapter-pvp",
            },
        )
        self.service.add_participant(
            "adapter-pvp",
            participant_id="u1",
            user_id="u1",
            amount=20,
            metadata={"role": "player", "nickname": "甲", "alive": True},
        )
        self.service.freeze_participant("adapter-pvp", "u1")

        roulette._restore_pvp_round(self.service.get_round("adapter-pvp"), self.service)

        self.assertEqual(
            roulette.pvp_games["g1"]["players"],
            [{"user_id": "u1", "nickname": "甲", "alive": True}],
        )

    async def test_ink_stargaze_finishes_pending_auxiliary_charge_on_restore(self):
        self._credit(ASSET_WINE_MONEY, "u1", 200)
        self.service.create_round(
            round_id="adapter-ink",
            game_type=taibai_tavern.INK_GAME_TYPE,
            mode="personal",
            group_id="g1",
            creator_id="u1",
            asset_type=ASSET_WINE_MONEY,
            payload={
                "options": ["酒", "月", "剑"],
                "treasure": "月",
                "excluded": [],
                "stargazed": False,
                "stake_wine": 50,
                "user_id": "u1",
                "group_id": "g1",
                "nickname": "甲",
            },
            participants=[{"user_id": "u1", "amount": 50}],
        )
        self.service.freeze_participant("adapter-ink", "u1")
        self.service.add_participant(
            "adapter-ink",
            participant_id="stargaze:u1",
            user_id="u1",
            amount=30,
            metadata={"role": "auxiliary", "kind": "stargaze", "revealed": "剑"},
        )
        self.service.freeze_participant("adapter-ink", "stargaze:u1")

        taibai_tavern._restore_ink_round(self.service.get_round("adapter-ink"), self.service)

        restored = taibai_tavern.active_ink_traces["g1_u1"]
        stored = self.service.get_round("adapter-ink")
        self.assertTrue(restored["stargazed"])
        self.assertEqual(restored["excluded"], ["剑"])
        self.assertEqual(stored["participants"]["stargaze:u1"]["state"], "settled")
        self.assertEqual(
            get_balance(ASSET_WINE_MONEY, "u1", "g1", store_path=self.wine_path),
            120,
        )


if __name__ == "__main__":
    unittest.main()
