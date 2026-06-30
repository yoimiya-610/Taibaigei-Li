from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common import feature_flags


class LegacyGameScheduleTest(unittest.TestCase):
    def test_weekday_rotation_matches_order(self):
        monday = date(2026, 6, 29)
        tuesday = date(2026, 6, 30)
        friday = date(2026, 7, 3)

        self.assertTrue(feature_flags.is_legacy_game_scheduled("legacy_slot", monday))
        self.assertFalse(feature_flags.is_legacy_game_scheduled("legacy_dice", monday))
        self.assertTrue(feature_flags.is_legacy_game_scheduled("legacy_dice", tuesday))
        self.assertTrue(feature_flags.is_legacy_game_scheduled("legacy_roulette", friday))

    def test_weekend_opens_all_legacy_games(self):
        saturday = date(2026, 7, 4)

        for feature in feature_flags.LEGACY_GAME_ORDER:
            self.assertTrue(feature_flags.is_legacy_game_scheduled(feature, saturday))

    def test_manual_override_expires_on_next_day(self):
        monday = date(2026, 6, 29)
        tuesday = date(2026, 6, 30)

        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                with patch.object(feature_flags, "_rotation_token", return_value=monday.isoformat()):
                    feature_flags.set_feature_enabled("legacy_race", True)

                self.assertTrue(feature_flags.get_legacy_game_enabled("legacy_race", monday))
                self.assertIsNone(feature_flags.get_legacy_game_override("legacy_race", tuesday))
                self.assertFalse(feature_flags.get_legacy_game_enabled("legacy_race", tuesday))


if __name__ == "__main__":
    unittest.main()
