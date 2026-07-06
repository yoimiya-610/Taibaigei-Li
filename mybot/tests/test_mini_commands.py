from pathlib import Path
import tempfile
import unittest

import mybot.bot  # noqa: F401
from mybot.common import charm, gift_store
from mybot.plugins import mini_commands


class MiniCommandsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_gift_file = gift_store.GIFT_INVENTORY_FILE
        self.old_charm_file = charm.CHARM_FILE
        gift_store.GIFT_INVENTORY_FILE = Path(self.temp_dir.name) / "gift_inventory.json"
        charm.CHARM_FILE = Path(self.temp_dir.name) / "charm.json"

    def tearDown(self):
        gift_store.GIFT_INVENTORY_FILE = self.old_gift_file
        charm.CHARM_FILE = self.old_charm_file
        self.temp_dir.cleanup()

    def test_flight_consumes_cup_and_adds_self_charm(self):
        gift_store.add_gift_item("10001", "20002", "flight_cup", 1)

        result = mini_commands.use_flight_cup_on_self("10001", "20002")
        inventory = gift_store.get_gift_inventory("10001", "20002")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["gift"]["name"], "神秘的杯子")
        self.assertEqual(result["quantity"], 0)
        self.assertEqual(result["charm_gain"], 120)
        self.assertEqual(charm.get_charm("10001", "20002"), 120)
        self.assertNotIn("flight_cup", inventory["items"])

    def test_flight_requires_cup_inventory(self):
        result = mini_commands.use_flight_cup_on_self("10001", "20002")

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["gift"]["id"], "flight_cup")
        self.assertEqual(charm.get_charm("10001", "20002"), 0)


if __name__ == "__main__":
    unittest.main()
