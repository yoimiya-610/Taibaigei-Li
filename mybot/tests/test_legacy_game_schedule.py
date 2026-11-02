from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common import feature_flags


class LegacyGameScheduleTest(unittest.TestCase):
    def test_all_days_default_to_closed(self):
        monday = date(2026, 6, 29)
        tuesday = date(2026, 6, 30)
        saturday = date(2026, 7, 4)
        sunday = date(2026, 7, 5)

        for day in (monday, tuesday, saturday, sunday):
            for feature in feature_flags.LEGACY_GAME_ORDER:
                self.assertFalse(feature_flags.is_legacy_game_scheduled(feature, day))
                self.assertFalse(feature_flags.get_legacy_game_enabled(feature, day))

    def test_explicit_enable_persists_across_days(self):
        monday = date(2026, 6, 29)
        tuesday = date(2026, 6, 30)

        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                with patch.object(feature_flags, "_rotation_token", return_value=monday.isoformat()):
                    feature_flags.set_feature_enabled("legacy_race", True)

                self.assertTrue(feature_flags.get_legacy_game_enabled("legacy_race", monday))
                self.assertTrue(feature_flags.get_legacy_game_override("legacy_race", tuesday))
                self.assertTrue(feature_flags.get_legacy_game_enabled("legacy_race", tuesday))

    def test_new_write_preserves_existing_explicit_overrides(self):
        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                feature_flags.set_feature_enabled("legacy_slot", True, "100")
                feature_flags.set_feature_enabled("legacy_dice", True, "200")

                self.assertTrue(
                    feature_flags.get_legacy_game_enabled("legacy_slot", group_id="100")
                )
                self.assertTrue(
                    feature_flags.get_legacy_game_enabled("legacy_dice", group_id="200")
                )


if __name__ == "__main__":
    unittest.main()
