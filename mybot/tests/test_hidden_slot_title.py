from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common import titles


class HiddenSlotTitleTest(unittest.TestCase):
    def test_record_slot_grape_or_better_updates_metric(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with patch.object(titles, "TITLE_DATA_FILE", base / "titles.json"), patch.object(
                titles, "SLOT_STATS_FILE", base / "slot_stats.json"
            ), patch.object(titles, "CLASSICS_FILE", base / "classics.json"), patch.object(
                titles, "FORTUNE_FILE", base / "fortune_data.json"
            ), patch.object(
                titles, "MONTHLY_FAME_FILE", base / "monthly_fame.json"
            ):
                count = titles.record_slot_grape_or_better("10001", "20001")
                self.assertEqual(count, 1)

                metrics = titles.collect_title_metrics(
                    "10001",
                    "20001",
                    {"current": 0, "total": 0},
                )
                self.assertEqual(metrics["slot_grape_or_better_count"], 1)

                unlocked = titles._achieved_title_ids(metrics)
                self.assertIn("secret_slot_grape", unlocked)


if __name__ == "__main__":
    unittest.main()
