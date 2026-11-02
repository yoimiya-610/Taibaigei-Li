import ast
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from mybot.common import streak, titles
from mybot.plugins import fortune, mini_commands
from mybot.plugins._fortune import advice, copy


class FortuneOverhaulTest(unittest.TestCase):
    def test_fortune_item_tables_have_two_hundred_reviewed_unique_items(self):
        self.assertIs(fortune.YI_ITEMS, advice.YI_ITEMS)
        self.assertEqual(len(fortune.YI_ITEMS), 200)
        self.assertEqual(len(set(fortune.YI_ITEMS)), 200)
        self.assertIn("起飞", fortune.YI_ITEMS)
        self.assertNotIn("温习一张草图", fortune.YI_ITEMS)
        self.assertNotIn("复盘一篇文章", fortune.YI_ITEMS)

        self.assertIs(fortune.JI_ITEMS, advice.JI_ITEMS)
        self.assertEqual(len(fortune.JI_ITEMS), 200)
        self.assertEqual(len(set(fortune.JI_ITEMS)), 200)
        self.assertIn("诋毁悠依米亚", fortune.JI_ITEMS)

    def test_fortune_item_tables_are_explicit_string_literals(self):
        source_path = Path(advice.__file__)
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        assignments = {
            node.targets[0].id: node.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        }

        for name in ("YI_ITEMS", "JI_ITEMS"):
            table = assignments[name]
            self.assertIsInstance(table, ast.List)
            self.assertTrue(
                all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str)
                    for item in table.elts
                )
            )

        self.assertFalse(hasattr(copy, "YI_ITEMS"))
        self.assertFalse(hasattr(copy, "JI_ITEMS"))

    def test_china_captain_title_requires_today_flight_fortune(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fortune_file = base / "fortune_data.json"
            title_file = base / "titles.json"
            fortune_file.write_text(
                json.dumps(
                    {
                        "fortune_record": {
                            streak.fortune_record_key("2026-07-09", "10001", "20001"): {
                                "yi": ["起飞", "整理钥匙", "听歌"],
                            },
                            streak.fortune_record_key("2026-07-09", "10002", "20001"): {
                                "yi": ["整理钥匙", "听歌", "喝一杯热茶"],
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(streak, "DATA_FILE", fortune_file), patch.object(
                titles, "TITLE_DATA_FILE", title_file
            ), patch.object(
                titles, "SLOT_STATS_FILE", base / "slot_stats.json"
            ), patch.object(
                titles, "CLASSICS_FILE", base / "classics.json"
            ), patch.object(
                titles, "FORTUNE_FILE", fortune_file
            ), patch.object(
                titles, "MONTHLY_FAME_FILE", base / "monthly_fame.json"
            ), patch.object(
                titles, "GIFT_STATS_FILE", base / "gift_title_stats.json"
            ), patch.object(
                streak, "datetime"
            ) as datetime_mock:
                datetime_mock.now.return_value.date.return_value = date(2026, 7, 9)

                title = mini_commands.grant_china_captain_if_eligible("10001", "20001")
                missing = mini_commands.grant_china_captain_if_eligible("10002", "20001")

                self.assertIsNotNone(title)
                self.assertEqual(title.title, "中国机长")
                self.assertIsNone(missing)

                data = json.loads(title_file.read_text(encoding="utf-8"))
                self.assertIn("secret_china_captain", data["users"]["20001_10001"]["unlocked"])
                self.assertNotIn("20001_10002", data["users"])


if __name__ == "__main__":
    unittest.main()
