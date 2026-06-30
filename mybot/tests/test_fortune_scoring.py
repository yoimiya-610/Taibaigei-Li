from datetime import date
from pathlib import Path
import tempfile
import unittest

import mybot.bot  # noqa: F401
from mybot.plugins import fortune
from mybot.plugins import points


class FortuneScoringTest(unittest.TestCase):
    def test_fortune_base_points_are_increased_by_ten(self):
        self.assertEqual(
            fortune.FORTUNE_POINTS,
            {
                fortune.UNKNOWN_FORTUNE_NAME: 10000,
                "天命之子": 120,
                "大吉": 70,
                "中吉": 50,
                "小吉": 40,
                "吉": 35,
                "末吉": 30,
                "小凶": 25,
                "中凶": 23,
                "大凶": 120,
            },
        )

    def test_streak_multiplier_is_linear_and_capped(self):
        self.assertEqual(fortune.get_streak_multiplier_tenths(0), 10)
        self.assertEqual(fortune.get_streak_multiplier_tenths(2), 10)
        self.assertEqual(fortune.get_streak_multiplier_tenths(3), 11)
        self.assertEqual(fortune.get_streak_multiplier_tenths(184), 21)
        self.assertEqual(fortune.get_streak_multiplier_tenths(365), 30)
        self.assertEqual(fortune.get_streak_multiplier_tenths(999), 30)

        values = [fortune.get_streak_multiplier_tenths(day) for day in range(3, 366)]
        self.assertEqual(values, sorted(values))

    def test_streak_multiplier_applies_to_points(self):
        self.assertEqual(fortune.apply_streak_multiplier(120, 10), 120)
        self.assertEqual(fortune.apply_streak_multiplier(120, 11), 132)
        self.assertEqual(fortune.apply_streak_multiplier(120, 30), 360)
        self.assertEqual(fortune.get_streak_bonus(3, 120), 12)

    def test_unknown_fortune_keeps_fixed_reward(self):
        score = fortune.calculate_fortune_score(fortune.UNKNOWN_FORTUNE_NAME, 365, None)

        self.assertEqual(score["base_points"], 10000)
        self.assertEqual(score["total_points"], 10000)
        self.assertEqual(score["streak_multiplier"], 10)

    def test_daily_fortune_is_stable_for_date(self):
        first = fortune.get_daily_fortune("123456", date(2026, 6, 29))
        second = fortune.get_daily_fortune("123456", date(2026, 6, 29))

        self.assertEqual(first, second)

    def test_add_points_once_is_idempotent(self):
        old_points_file = points.POINTS_FILE
        with tempfile.TemporaryDirectory() as tmp_dir:
            points.POINTS_FILE = Path(tmp_dir) / "points.json"
            try:
                first = points.add_points_once("10001", "20002", 50, "fortune:test")
                second = points.add_points_once("10001", "20002", 50, "fortune:test")
                points_info = points.get_points("10001", "20002")
            finally:
                points.POINTS_FILE = old_points_file

        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(points_info["current"], 50)
        self.assertEqual(points_info["total"], 50)


if __name__ == "__main__":
    unittest.main()
