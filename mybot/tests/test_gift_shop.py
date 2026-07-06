import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mybot.common import gift_store


class GiftShopTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_file = gift_store.GIFT_INVENTORY_FILE
        gift_store.GIFT_INVENTORY_FILE = Path(self.temp_dir.name) / "gift_inventory.json"

    def tearDown(self):
        gift_store.GIFT_INVENTORY_FILE = self.original_file
        self.temp_dir.cleanup()

    def test_daily_shop_is_stable_within_same_day(self):
        now = datetime(2026, 6, 30, 10, 0, 0)
        first = gift_store.get_daily_gift_shop("2001", now=now)
        second = gift_store.get_daily_gift_shop("2001", now=now)

        self.assertEqual(first["date"], "2026-06-30")
        self.assertEqual(len(first["offers"]), 3)
        self.assertEqual(
            [(offer["gift_id"], offer["price"]) for offer in first["offers"]],
            [(offer["gift_id"], offer["price"]) for offer in second["offers"]],
        )

        for offer in first["offers"]:
            gift = offer["gift"]
            self.assertGreaterEqual(offer["price"], 1)
            base_price = gift["other_charm"] / gift_store.GIFT_SHOP_PRICE_PER_POINT_CHARM
            self.assertGreaterEqual(offer["price"], int(base_price * 0.8))
            self.assertLessEqual(offer["price"], int(base_price * 1.2) + 1)

    def test_purchase_daily_shop_gift_allows_one_per_item_per_day(self):
        now = datetime(2026, 6, 30, 10, 0, 0)
        shop = gift_store.get_daily_gift_shop("2001", now=now)
        first_gift_id = shop["offers"][0]["gift_id"]
        second_gift_id = shop["offers"][1]["gift_id"]

        first = gift_store.purchase_daily_shop_gift("1001", "2001", first_gift_id, now=now)
        second = gift_store.purchase_daily_shop_gift("1001", "2001", second_gift_id, now=now)
        third = gift_store.purchase_daily_shop_gift("1001", "2001", first_gift_id, now=now)

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(third["status"], "already_purchased")
        self.assertEqual(third["gift_id"], first_gift_id)
        inventory = gift_store.get_gift_inventory("1001", "2001")
        self.assertEqual(inventory["items"], {first_gift_id: 1, second_gift_id: 1})

    def test_purchase_daily_shop_gifts_buys_remaining_offers_together(self):
        now = datetime(2026, 6, 30, 10, 0, 0)
        shop = gift_store.get_daily_gift_shop("2001", "1001", now=now)
        selected_ids = [offer["gift_id"] for offer in shop["offers"]]

        result = gift_store.purchase_daily_shop_gifts("1001", "2001", selected_ids, now=now)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(
            [item["gift_id"] for item in result["results"]],
            selected_ids,
        )
        self.assertEqual(
            gift_store.get_gift_inventory("1001", "2001")["items"],
            {gift_id: 1 for gift_id in selected_ids},
        )
        refreshed_shop = gift_store.get_daily_gift_shop("2001", "1001", now=now)
        self.assertEqual(refreshed_shop["purchased_gift_ids"], sorted(selected_ids))

    def test_flight_cup_keeps_fixed_shop_price(self):
        now = datetime(2026, 6, 30, 10, 0, 0)
        original_offers = gift_store._build_daily_shop_offers

        def fake_offers(group_id: str, day_text: str) -> list[dict]:
            return [{"gift_id": "flight_cup", "price": 200, "multiplier": 1.0}]

        gift_store._build_daily_shop_offers = fake_offers
        try:
            shop = gift_store.get_daily_gift_shop("2001", now=now)
        finally:
            gift_store._build_daily_shop_offers = original_offers

        self.assertEqual(len(shop["offers"]), 1)
        self.assertEqual(shop["offers"][0]["gift_id"], "flight_cup")
        self.assertEqual(shop["offers"][0]["price"], 200)


if __name__ == "__main__":
    unittest.main()
