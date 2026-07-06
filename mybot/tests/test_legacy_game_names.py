import importlib
import unittest

import mybot.bot  # noqa: F401
from mybot.common import feature_flags
from mybot.common.legacy_games import LEGACY_GAMES, LEGACY_GAME_BY_KEY
from mybot.plugins import game_disabled
from mybot.plugins import help as help_plugin


class LegacyGameNamesTest(unittest.TestCase):
    def test_feature_names_match_legacy_game_metadata(self):
        for game in LEGACY_GAMES:
            self.assertEqual(feature_flags.get_feature_name(game.feature_key), game.display_name)
            self.assertIs(LEGACY_GAME_BY_KEY[game.feature_key], game)

    def test_status_and_game_hall_use_same_display_names(self):
        status_text = game_disabled._render_game_status()
        game_text = help_plugin._render_game_list()

        for game in LEGACY_GAMES:
            self.assertIn(f"｜{game.display_name}", status_text)
            self.assertIn(f"【{game.display_name}｜", game_text)
            self.assertIn("；".join(game.usage), game_text)

    def test_game_hall_does_not_show_legacy_mismatched_names(self):
        game_text = help_plugin._render_game_list()

        self.assertNotIn("【多人转盘", game_text)
        self.assertNotIn("旧式转盘", game_text)
        self.assertNotIn("/点数挑战", game_text)
        self.assertNotIn("/竞速", game_text)

    def test_disabled_plugin_help_items_use_primary_names(self):
        for game in LEGACY_GAMES:
            module = importlib.import_module(f"mybot.plugins_disabled.{game.module_name}")
            expected_help = f"{game.primary_command} - {game.display_name}"

            self.assertEqual(module.HELP_ITEMS[0].text, expected_help)
            self.assertEqual(module.HELP_ITEMS[0].order, game.help_order)
            self.assertEqual(module.COMMAND_ALIASES[0], game.display_name)


if __name__ == "__main__":
    unittest.main()
