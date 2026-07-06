from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common import gift_store, monthly_fame


class _DummyTitle:
    def __init__(self, title_id: str, title: str):
        self.id = title_id
        self.title = title


class MonthlyFameGiftTest(unittest.TestCase):
    def test_settle_monthly_fame_grants_rank_gifts_once(self):
        rankings = [
            {"user_id": "1001", "score": 88},
            {"user_id": "1002", "score": 66},
            {"user_id": "1003", "score": 44},
        ]

        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with patch.object(monthly_fame, "FAME_FILE", base / "monthly_fame.json"), patch.object(
                gift_store, "GIFT_INVENTORY_FILE", base / "gift_inventory.json"
            ), patch.object(monthly_fame, "calculate_monthly_fame", return_value=rankings), patch.object(
                monthly_fame,
                "grant_title",
                side_effect=[
                    _DummyTitle("monthly_fame_first", "月榜风云魁首"),
                    _DummyTitle("monthly_fame_second", "月榜凌云客"),
                    _DummyTitle("monthly_fame_third", "月榜探花郎"),
                ],
            ):
                result = monthly_fame.settle_monthly_fame("2001", "2026-06")
                self.assertFalse(result["already"])
                self.assertEqual(
                    [(award["rank"], award["gift_id"]) for award in result["awards"]],
                    [(1, "crown"), (2, "perfume"), (3, "star_lantern")],
                )

                first_inventory = gift_store.get_gift_inventory("1001", "2001")
                second_inventory = gift_store.get_gift_inventory("1002", "2001")
                third_inventory = gift_store.get_gift_inventory("1003", "2001")
                self.assertEqual(first_inventory["items"], {"crown": 1})
                self.assertEqual(second_inventory["items"], {"perfume": 1})
                self.assertEqual(third_inventory["items"], {"star_lantern": 1})

                again = monthly_fame.settle_monthly_fame("2001", "2026-06")
                self.assertTrue(again["already"])
                self.assertEqual(gift_store.get_gift_inventory("1001", "2001")["items"], {"crown": 1})
                self.assertEqual(gift_store.get_gift_inventory("1002", "2001")["items"], {"perfume": 1})
                self.assertEqual(gift_store.get_gift_inventory("1003", "2001")["items"], {"star_lantern": 1})


if __name__ == "__main__":
    unittest.main()
