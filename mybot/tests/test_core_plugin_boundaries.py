from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import mybot.bot  # noqa: F401
from mybot.plugins import fortune, gift, taibai_tavern


class CorePluginBoundaryTest(unittest.TestCase):
    def test_command_handlers_stay_in_stable_plugin_modules(self):
        self.assertEqual(fortune.handle_fortune.__module__, "mybot.plugins.fortune")
        self.assertEqual(gift.handle_send_gift.__module__, "mybot.plugins.gift")
        self.assertEqual(
            taibai_tavern.handle_start_flip.__module__,
            "mybot.plugins.taibai_tavern",
        )

    def test_business_rules_are_reexported_from_private_modules(self):
        self.assertEqual(
            fortune.calculate_fortune_score.__module__,
            "mybot.plugins._fortune.rules",
        )
        self.assertEqual(
            gift._resolve_gift_name.__module__,
            "mybot.plugins._gift.rules",
        )
        self.assertEqual(
            taibai_tavern.calculate_reward_wine.__module__,
            "mybot.plugins._taibai_tavern.rules",
        )
        self.assertEqual(
            taibai_tavern.create_rps_duel_round.__module__,
            "mybot.plugins._taibai_tavern.business",
        )

    def test_storage_facades_honor_existing_plugin_data_paths(self):
        old_tavern_file = taibai_tavern.DATA_FILE
        old_flower_file = gift.FLOWER_GIFTS_FILE
        try:
            with TemporaryDirectory() as tmp_dir:
                base = Path(tmp_dir)
                taibai_tavern.DATA_FILE = base / "taibai_tavern.json"
                gift.FLOWER_GIFTS_FILE = base / "flower_gifts.json"

                taibai_tavern.add_wine_money("10001", "20001", 30)
                reservation = gift._reserve_daily_flower(
                    "20001",
                    "10001",
                    "10002",
                    10,
                )

                self.assertIsNone(reservation)
                self.assertEqual(taibai_tavern.get_wine_money("10001", "20001"), 30)
                self.assertTrue(taibai_tavern.DATA_FILE.exists())
                self.assertTrue(gift.FLOWER_GIFTS_FILE.exists())
        finally:
            taibai_tavern.DATA_FILE = old_tavern_file
            gift.FLOWER_GIFTS_FILE = old_flower_file


if __name__ == "__main__":
    unittest.main()
