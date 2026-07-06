from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from mybot.plugins import fortune
from mybot.plugins import points
from mybot.common import titles


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

    def test_title_power_can_double_unknown_fortune_reward(self):
        score = fortune.calculate_fortune_score(
            fortune.UNKNOWN_FORTUNE_NAME,
            365,
            None,
            title_bonus={
                "title": "气运之神",
                "rarity": "UR",
                "trigger_rate": 4,
                "activated": True,
            },
        )

        self.assertEqual(score["base_points"], 10000)
        self.assertEqual(score["total_points"], 20000)
        self.assertIn("积分翻倍", score["title_power_text"])

    def test_title_rarity_mapping_matches_difficulty(self):
        self.assertEqual(titles.get_title_rarity(titles.TITLE_BY_ID["default"]), "R")
        self.assertEqual(titles.get_title_rarity(titles.TITLE_BY_ID["points_5000"]), "SR")
        self.assertEqual(titles.get_title_rarity(titles.TITLE_BY_ID["streak_365"]), "UR")
        self.assertEqual(titles.get_title_rarity(titles.TITLE_BY_ID["secret_flight_cup_misgift"]), "UR")

    def test_daily_fortune_is_stable_for_date(self):
        first = fortune.get_daily_fortune("123456", date(2026, 6, 29))
        second = fortune.get_daily_fortune("123456", date(2026, 6, 29))

        self.assertEqual(first, second)

    def test_makeup_refreshes_today_existing_streak_record(self):
        from mybot.common import streak as streak_module

        old_fortune_file = fortune.DATA_FILE
        old_streak_file = streak_module.DATA_FILE
        user_id = "10001"
        group_id = "20002"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                data_file = Path(tmp_dir) / "fortune_data.json"
                fortune.DATA_FILE = data_file
                streak_module.DATA_FILE = data_file

                data = {
                    "fortune_record": {},
                    "streak": {},
                    "makeup_records": {},
                    "makeup_usage": {},
                }
                for day in range(8, 29):
                    date_text = f"2026-06-{day:02d}"
                    data["fortune_record"][fortune._fortune_record_key(date_text, user_id, group_id)] = {
                        "fortune": "吉",
                    }

                today_key = fortune._fortune_record_key("2026-06-30", user_id, group_id)
                data["fortune_record"][today_key] = {
                    "date": "2026-06-30",
                    "user_id": user_id,
                    "group_id": group_id,
                    "fortune": "吉",
                    "emoji": "🍀",
                    "desc": "旧签已有。",
                    "poem": "今日先断作一签。",
                    "base_points": 35,
                    "total_points": 35,
                    "streak_count": 1,
                    "streak_multiplier": 10,
                    "points_awarded": True,
                    "award_tx_id": f"fortune:{today_key}",
                }
                fortune.save_data(data)

                now = datetime(2026, 6, 30, 12, 0, tzinfo=fortune.APP_TIMEZONE)
                with patch.object(fortune, "current_datetime", return_value=now):
                    result = fortune._apply_makeup(user_id, group_id, 10)
                saved_record = fortune.load_data()["fortune_record"][today_key]
        finally:
            fortune.DATA_FILE = old_fortune_file
            streak_module.DATA_FILE = old_streak_file

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["target_date"], "2026-06-29")
        self.assertEqual(result["streak_count"], 23)
        self.assertTrue(result["today_record_repaired"])
        self.assertEqual(saved_record["streak_count_before_makeup"], 1)
        self.assertEqual(saved_record["streak_count"], 23)
        self.assertTrue(saved_record["streak_repaired_by_makeup"])
        self.assertEqual(saved_record["total_points"], 35)

        rendered = fortune._render_full_fortune("测试群友", saved_record)
        self.assertIn("连续签到 23 天", rendered)
        self.assertIn("补签已续上", rendered)

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
