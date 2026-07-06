import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import nonebot


nonebot.init()


class GiftInventoryTest(unittest.TestCase):
    def setUp(self):
        import mybot.bot  # noqa: F401

        from mybot.common import gift_store
        from mybot.plugins import gift

        self.gift = gift
        self.gift_store = gift_store
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_file = self.gift_store.GIFT_INVENTORY_FILE
        self.gift_store.GIFT_INVENTORY_FILE = Path(self.temp_dir.name) / "gift_inventory.json"
        self.gift.GIFT_INVENTORY_FILE = self.gift_store.GIFT_INVENTORY_FILE

    def tearDown(self):
        self.gift_store.GIFT_INVENTORY_FILE = self.original_file
        self.gift.GIFT_INVENTORY_FILE = self.original_file
        self.temp_dir.cleanup()

    def test_draw_daily_gift_only_allows_one_draw_per_day(self):
        now = datetime(2026, 6, 29, 12, 0, 0)
        first = self.gift.draw_daily_gift("1001", "2001", now=now, rng=random.Random(0))
        second = self.gift.draw_daily_gift("1001", "2001", now=now, rng=random.Random(1))

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "already_drawn")

        record = self.gift.get_gift_inventory("1001", "2001")
        self.assertEqual(sum(record["items"].values()), 1)
        self.assertEqual(record["last_draw_date"], "2026-06-29")

    def test_consume_gift_item_decrements_inventory(self):
        self.gift.add_gift_item("1001", "2001", "milk_tea", 2)

        first = self.gift.consume_gift_item("1001", "2001", "milk_tea")
        second = self.gift.consume_gift_item("1001", "2001", "milk_tea")
        third = self.gift.consume_gift_item("1001", "2001", "milk_tea")

        self.assertEqual(first, {"status": "ok", "quantity": 1})
        self.assertEqual(second, {"status": "ok", "quantity": 0})
        self.assertEqual(third, {"status": "missing", "quantity": 0})

    def test_gift_expected_charm_ratio_stays_below_send_flower(self):
        total_weight = sum(item["weight"] for item in self.gift.GIFT_POOL)
        expected_charm = sum(item["weight"] * item["other_charm"] for item in self.gift.GIFT_POOL) / total_weight
        expected_ratio = expected_charm / self.gift.DAILY_GIFT_DRAW_COST

        self.assertAlmostEqual(expected_ratio, 0.6, places=2)

    def test_self_target_requires_supported_gift(self):
        unsupported = self.gift._resolve_gift_name("梅香饭团")
        supported = self.gift._resolve_gift_name("云顶奶茶")

        self.assertEqual(unsupported["self_charm"], 0)
        self.assertGreater(supported["self_charm"], 0)

    def test_flight_cup_is_self_favoring_rare_gift(self):
        item = self.gift._resolve_gift_name("神秘的杯子")

        self.assertIsNotNone(item)
        self.assertEqual(item["shop_price"], 200)
        self.assertEqual(item["rarity"], "SSR")
        self.assertEqual(item["weight"], 5)
        self.assertEqual(item["other_charm"], -20)
        self.assertEqual(item["self_charm"], 120)

    def test_daily_shop_text_hides_price_formula(self):
        shop = self.gift._render_daily_shop_text("2001", "1001")

        self.assertNotIn("价签按 1 积分约抵", shop)

    def test_render_new_title_notice_includes_hidden_titles(self):
        notice = self.gift._render_new_title_notice({"new_ids": ["secret_flight_cup_misgift"]})

        self.assertIn("天外名号", notice)
        self.assertIn("起飞失败", notice)

if __name__ == "__main__":
    unittest.main()
