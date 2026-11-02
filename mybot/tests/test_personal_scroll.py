import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401

from mybot.common.gift_store import get_gift_inventory_snapshot
from mybot.common.command_discovery import search_public_commands
from mybot.common.personal_scroll import (
    PersonalScrollProvider,
    PersonalScrollRegistry,
    PersonalScrollSection,
    render_personal_scroll,
)
from mybot.common.public_contributions import get_public_contribution_stats
from mybot.plugins import my_scroll


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class PublicContributionStatsTest(unittest.TestCase):
    def test_counts_only_active_public_user_contributions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            classics_file = root / "classics.json"
            poetry_file = root / "poetry_society.json"
            image_root = root / "image_library"
            _write_json(
                classics_file,
                {
                    "groups": {
                        "20001": {
                            "classics": {
                                "10001": [
                                    {"speaker_id": "10001", "recorder_id": "10002"},
                                    {"speaker_id": "10001", "recorder_id": "10001"},
                                ],
                                "10002": [
                                    {"speaker_id": "10002", "recorder_id": "10001"},
                                ],
                            }
                        }
                    }
                },
            )
            _write_json(
                poetry_file,
                {
                    "schema_version": 1,
                    "groups": {
                        "20001": {
                            "weeks": {
                                "2026-W28": {
                                    "submissions": {
                                        "1": {"author_id": "10001", "status": "active"},
                                        "2": {"author_id": "10001", "status": "withdrawn"},
                                        "3": {"author_id": "10002", "status": "active"},
                                    }
                                }
                            }
                        }
                    },
                },
            )
            _write_json(
                image_root / "20001" / "index.json",
                {
                    "version": 1,
                    "next_id": 4,
                    "images": [
                        {"id": 1, "saved_by": "10001"},
                        {"id": 2, "saved_by": "10002"},
                        {"id": 3, "saved_by": "10001"},
                    ],
                },
            )

            stats = get_public_contribution_stats(
                "10001",
                "20001",
                classics_file=classics_file,
                poetry_file=poetry_file,
                image_root=image_root,
            )

        self.assertEqual(
            stats,
            {
                "quote_speaker_count": 2,
                "quote_recorder_count": 2,
                "poetry_submission_count": 1,
                "image_saved_count": 2,
                "total": 7,
            },
        )


class PersonalScrollTest(unittest.TestCase):
    def test_render_unifies_all_existing_personal_systems(self):
        with (
            patch(
                "mybot.common.personal_scroll.get_points",
                return_value={"current": 88, "total": 520},
            ),
            patch("mybot.common.personal_scroll.get_wine_money", return_value=66),
            patch(
                "mybot.common.personal_scroll.get_display_title",
                return_value={
                    "title": "月下留香客",
                    "rarity": "SR",
                    "unlocked_count": 7,
                    "total_count": 42,
                },
            ),
            patch("mybot.common.personal_scroll.get_charm", return_value=123),
            patch(
                "mybot.common.personal_scroll.get_gift_inventory_snapshot",
                return_value={"items": {"milk_tea": 2, "crown": 1}},
            ),
            patch(
                "mybot.common.personal_scroll.get_public_contribution_stats",
                return_value={
                    "quote_speaker_count": 2,
                    "quote_recorder_count": 3,
                    "poetry_submission_count": 4,
                    "image_saved_count": 5,
                    "total": 14,
                },
            ),
        ):
            text = render_personal_scroll("10001", "20001", "诗友甲")

        self.assertIn("💎 积分：当前 88｜累计获得 520", text)
        self.assertIn("🍶 酒钱：66", text)
        self.assertIn("🎖 称号：月下留香客 [SR]", text)
        self.assertIn("名号入册：7/42", text)
        self.assertIn("🌸 魅力：123", text)
        self.assertIn("🎁 礼物：3 件（2 种）", text)
        self.assertIn("云顶奶茶×2", text)
        self.assertIn("鎏金小冠×1", text)
        self.assertIn("入典 2 条｜执笔 3 条｜诗社 4 篇｜收图 5 幅", text)
        poem = text.split("『", 1)[1].rsplit("』", 1)[0]
        self.assertEqual(len(poem.splitlines()), 4)

    def test_registry_orders_future_sections_and_isolates_failures(self):
        registry = PersonalScrollRegistry()
        registry.register(
            PersonalScrollProvider(
                "later",
                20,
                lambda _user, _group: PersonalScrollSection(("后来的个人系统",)),
                "后来页暂缺",
            )
        )

        def broken_provider(_user_id: str, _group_id: str) -> PersonalScrollSection:
            raise RuntimeError("private detail")

        registry.register(
            PersonalScrollProvider("broken", 15, broken_provider, "坏页已合上")
        )
        registry.register(
            PersonalScrollProvider(
                "earlier",
                10,
                lambda _user, _group: PersonalScrollSection(("先来的个人系统",)),
                "先来页暂缺",
            )
        )

        sections = registry.collect("10001", "20001")

        self.assertEqual(
            [section.lines[0] for section in sections],
            ["先来的个人系统", "坏页已合上", "后来的个人系统"],
        )

    def test_inventory_snapshot_does_not_create_an_empty_store(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            inventory_file = Path(temporary_directory) / "gift_inventory.json"
            with patch("mybot.common.gift_store.GIFT_INVENTORY_FILE", inventory_file):
                record = get_gift_inventory_snapshot("10001", "20001")

            self.assertEqual(record["items"], {})
            self.assertFalse(inventory_file.exists())

    def test_help_aliases_and_private_copy_expose_the_scroll(self):
        self.assertEqual(
            my_scroll.HELP_ITEMS[0].text,
            "/我的卷册 - 汇总个人账册与公开贡献",
        )
        self.assertEqual(set(my_scroll.COMMAND_ALIASES), {"我的卷册", "卷册", "个人卷册"})
        poem = my_scroll.PRIVATE_MESSAGE.split("『", 1)[1].rsplit("』", 1)[0]
        self.assertEqual(len(poem.splitlines()), 4)

        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            results = search_public_commands("卷册")
        self.assertTrue(
            any(
                result.text == "/我的卷册 - 汇总个人账册与公开贡献"
                for result in results
            )
        )


if __name__ == "__main__":
    unittest.main()
