from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from mybot.common import feature_flags, runtime_state
from mybot.plugins import admin_console, fortune, fun, help as help_plugin, poem, points, practical_tools, translate


class SystemOptimizationTest(unittest.TestCase):
    def test_fuzzy_command_aliases_include_common_phrasings(self):
        self.assertIn("对对子", poem.COMMAND_ALIASES)
        self.assertIn("赏诗", poem.COMMAND_ALIASES)
        self.assertIn("今天吃啥", fun.COMMAND_ALIASES)
        self.assertIn("算一卦", fun.COMMAND_ALIASES)
        self.assertIn("今日签到", fortune.COMMAND_ALIASES)
        self.assertIn("命令列表", help_plugin.COMMAND_ALIASES)
        self.assertIn("查分", points.COMMAND_ALIASES)
        self.assertIn("低保", points.COMMAND_ALIASES)
        self.assertIn("翻译", translate.COMMAND_ALIASES)
        self.assertIn("总结", practical_tools.COMMAND_ALIASES)
        self.assertIn("润色", practical_tools.COMMAND_ALIASES)
        self.assertIn("解释", practical_tools.COMMAND_ALIASES)
        self.assertIn("凯撒", practical_tools.COMMAND_ALIASES)
        self.assertIn("摩斯", practical_tools.COMMAND_ALIASES)
        self.assertIn("栅栏", practical_tools.COMMAND_ALIASES)
        self.assertIn("维吉尼亚", practical_tools.COMMAND_ALIASES)
        self.assertIn("培根", practical_tools.COMMAND_ALIASES)
        self.assertIn("Base64", practical_tools.COMMAND_ALIASES)
        self.assertIn("URL编码", practical_tools.COMMAND_ALIASES)
        self.assertIn("Unicode", practical_tools.COMMAND_ALIASES)
        self.assertIn("二进制", practical_tools.COMMAND_ALIASES)

    def test_runtime_state_defaults_enabled_and_toggles(self):
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "runtime_state.json"
            with patch.object(runtime_state, "RUNTIME_STATE_FILE", state_path):
                self.assertTrue(runtime_state.is_bot_enabled())
                self.assertFalse(runtime_state.toggle_bot_enabled())
                self.assertFalse(runtime_state.is_bot_enabled())
                self.assertTrue(runtime_state.toggle_bot_enabled())
                self.assertTrue(runtime_state.is_bot_enabled())

    def test_debug_text_detection_keeps_debug_available_when_paused(self):
        self.assertTrue(admin_console._is_debug_command_text("/debug 1"))
        self.assertTrue(admin_console._is_debug_command_text("／debug 4"))
        self.assertFalse(admin_console._is_debug_command_text("/debug运势"))
        self.assertFalse(admin_console._is_debug_command_text("/签到"))

    def test_debug_amount_parser_accepts_positive_numbers_only(self):
        self.assertEqual(admin_console._parse_positive_amount("123"), 123)
        self.assertEqual(admin_console._parse_positive_amount("给 45 分"), 45)
        self.assertIsNone(admin_console._parse_positive_amount("0"))
        self.assertIsNone(admin_console._parse_positive_amount("-5"))
        self.assertIsNone(admin_console._parse_positive_amount("没有数字"))

    def test_debug_amount_parser_accepts_optional_group_id(self):
        self.assertEqual(
            admin_console._parse_debug_amount_and_group("给 45 分"),
            (45, None),
        )
        self.assertEqual(
            admin_console._parse_debug_amount_and_group("45 30001"),
            (45, "30001"),
        )
        self.assertIsNone(admin_console._parse_debug_amount_and_group("45 0"))
        self.assertIsNone(
            admin_console._parse_debug_amount_and_group("45 30001 40001")
        )

    def test_debug_legacy_games_toggle_sets_all_overrides(self):
        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                with patch.object(feature_flags, "_coerce_day", return_value=date(2026, 6, 29)):
                    enabled, _names = admin_console._toggle_all_legacy_games()
                    self.assertTrue(enabled)
                    for feature in feature_flags.LEGACY_GAME_ORDER:
                        self.assertTrue(feature_flags.get_legacy_game_override(feature))

                    enabled, _names = admin_console._toggle_all_legacy_games()
                    self.assertFalse(enabled)
                    for feature in feature_flags.LEGACY_GAME_ORDER:
                        self.assertFalse(feature_flags.get_legacy_game_override(feature))

    def test_debug_legacy_games_can_toggle_one_group_only(self):
        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(
                feature_flags,
                "LEGACY_GAME_OVERRIDES_FILE",
                overrides_path,
            ):
                with patch.object(
                    feature_flags,
                    "_coerce_day",
                    return_value=date(2026, 7, 16),
                ):
                    enabled, _names = admin_console._toggle_all_legacy_games("100")
                    self.assertTrue(enabled)
                    for feature in feature_flags.LEGACY_GAME_ORDER:
                        self.assertTrue(
                            feature_flags.get_legacy_game_override(
                                feature,
                                group_id="100",
                            )
                        )
                        self.assertIsNone(
                            feature_flags.get_legacy_game_override(
                                feature,
                                group_id="200",
                            )
                        )
                        self.assertIsNone(
                            feature_flags.get_legacy_game_override(feature)
                        )


if __name__ == "__main__":
    unittest.main()
