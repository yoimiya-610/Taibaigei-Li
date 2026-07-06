from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import mybot.bot  # noqa: F401
from mybot.plugins import points


class PointsLowIncomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.old_points_file = points.POINTS_FILE
        points.POINTS_FILE = Path(self.tmp_dir.name) / "points.json"

    def tearDown(self):
        points.POINTS_FILE = self.old_points_file
        self.tmp_dir.cleanup()

    def test_group_ranking_orders_by_total_points(self):
        points.save_points(
            {
                "20002_10001": {
                    "user_id": "10001",
                    "group_id": "20002",
                    "current": 500,
                    "total": 500,
                },
                "20002_10002": {
                    "user_id": "10002",
                    "group_id": "20002",
                    "current": 10,
                    "total": 1000,
                },
                "30003_10003": {
                    "user_id": "10003",
                    "group_id": "30003",
                    "current": 9999,
                    "total": 9999,
                },
            }
        )

        ranking = points.get_group_ranking("20002", 10)

        self.assertEqual([user["user_id"] for user in ranking], ["10002", "10001"])
        self.assertEqual(ranking[0]["total"], 1000)
        self.assertEqual(ranking[0]["current"], 10)

    def test_low_income_claim_adds_fixed_reward_once_per_day(self):
        first = points.claim_low_income("10001", "20002", today="2026-07-06")
        points.spend_points("10001", "20002", 70)
        second = points.claim_low_income("10001", "20002", today="2026-07-06")
        third = points.claim_low_income("10001", "20002", today="2026-07-07")
        points_info = points.get_points("10001", "20002")

        self.assertEqual(first["status"], "claimed")
        self.assertEqual(first["amount"], 100)
        self.assertEqual(second["status"], "already_claimed")
        self.assertEqual(second["amount"], 0)
        self.assertEqual(third["status"], "claimed")
        self.assertEqual(points_info["current"], 130)
        self.assertEqual(points_info["total"], 200)
        self.assertEqual(points_info["last_low_income_date"], "2026-07-07")

    def test_low_income_can_be_claimed_after_balance_drops_below_threshold(self):
        points.add_points("10001", "20002", 100)
        enough = points.claim_low_income("10001", "20002", today="2026-07-06")
        points.spend_points("10001", "20002", 1)
        claimed = points.claim_low_income("10001", "20002", today="2026-07-06")
        points_info = points.get_points("10001", "20002")

        self.assertEqual(enough["status"], "ineligible")
        self.assertNotIn("last_low_income_date", enough["record"])
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(points_info["current"], 199)
        self.assertEqual(points_info["total"], 200)


if __name__ == "__main__":
    unittest.main()
