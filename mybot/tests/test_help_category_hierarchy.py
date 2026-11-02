import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from mybot.common.feature_flags import collect_features
from mybot.common.help_registry import (
    CATEGORY_META,
    collect_public_command_names,
    render_category_help,
    render_help_menu,
)
from mybot.common.legacy_games import LEGACY_GAMES
from mybot.plugins import fun, game_disabled, image_library
from mybot.plugins import help as help_plugin


GAME_HELP_TEXT = "/游戏 - 查看历史小游戏玩法与开关"


class HelpCategoryHierarchyTest(unittest.TestCase):
    def test_command_overview_lists_public_entries_without_admin_commands(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            commands = collect_public_command_names()
            overview = help_plugin._render_command_overview()

        for command in ("运势", "签到", "小游戏", "小游戏状态", "唤醒", "起飞", "命令全览"):
            self.assertIn(command, commands)
        for command in (
            "功能列表",
            "管理员",
            "debug",
            "系统黑名单",
            "精华候选",
            "精华确认",
        ):
            self.assertNotIn(command, commands)
            self.assertNotIn(command, overview)
        self.assertNotIn(" - ", overview)
        self.assertEqual(overview.splitlines()[4:-1], ["｜".join(commands)])
        self.assertIn("/命令全览 - 查看全部命令", render_category_help("系统说明"))

    def test_root_menu_uses_fun_category_for_game_navigation(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            menu = render_help_menu()

        self.assertIn("🎭 【趣味功能】", menu)
        self.assertIn(GAME_HELP_TEXT, menu)
        self.assertNotIn("【小游戏】", menu)
        self.assertNotIn("/小游戏状态", menu)

        fun_section = menu.split("🎭 【趣味功能】", 1)[1].split("\n\n", 1)[0]
        visible_commands = [
            line for line in fun_section.splitlines() if line.startswith("/")
        ]
        self.assertEqual(
            visible_commands,
            [
                GAME_HELP_TEXT,
                "/图片库 - 收藏、检索与整理本群图片",
                "/骂我 - 文雅毒舌",
            ],
        )

    def test_fun_category_page_is_complete_stable_and_unique(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            category_page = render_category_help("趣味功能")

        self.assertIsNotNone(category_page)
        commands = [
            line for line in category_page.splitlines() if line.startswith("/")
        ]
        expected = [
            GAME_HELP_TEXT,
            *(item.text for item in image_library.HELP_ITEMS),
            *(item.text for item in fun.HELP_ITEMS),
        ]
        self.assertEqual(commands, expected)
        self.assertEqual(len(commands), len(set(commands)))
        self.assertNotIn(
            image_library.HELP_ITEMS[0].text,
            render_category_help("社交互动"),
        )

    def test_removed_game_category_has_no_metadata_or_page(self):
        self.assertNotIn("小游戏", CATEGORY_META)
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            self.assertIsNone(render_category_help("小游戏"))

    def test_fun_feature_filter_does_not_hide_game_navigation(self):
        def is_enabled(feature: str) -> bool:
            return feature != "fun"

        with patch(
            "mybot.common.help_registry.is_feature_enabled",
            side_effect=is_enabled,
        ):
            category_page = render_category_help("趣味功能")

        self.assertIsNotNone(category_page)
        self.assertIn(GAME_HELP_TEXT, category_page)
        self.assertNotIn("/骂我 - 文雅毒舌", category_page)

    def test_game_commands_aliases_and_status_navigation_remain_compatible(self):
        self.assertTrue(
            {"游戏", "游戏列表", "小游戏", "游戏大厅", "游戏大全"}.issubset(
                help_plugin.COMMAND_ALIASES
            )
        )
        self.assertEqual(
            set(game_disabled.COMMAND_ALIASES),
            {"小游戏状态", "历史小游戏"},
        )

        game_page = help_plugin._render_game_list()
        self.assertIn("/小游戏状态 - 查看六种游戏开关", game_page)
        for game in LEGACY_GAMES:
            self.assertIn(game.display_name, game_page)
            for usage in game.usage:
                self.assertIn(usage, game_page)

        status_feature = next(
            item for item in collect_features() if item["key"] == "game_disabled"
        )
        self.assertTrue(status_feature["public"])


if __name__ == "__main__":
    unittest.main()
