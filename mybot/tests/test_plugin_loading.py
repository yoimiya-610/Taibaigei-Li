import os
import unittest
from unittest.mock import patch


class PluginLoadingTest(unittest.TestCase):
    def test_plugins_load_once_under_package_names(self):
        import nonebot
        import mybot.bot  # noqa: F401

        module_names = {plugin.module_name for plugin in nonebot.get_loaded_plugins()}

        self.assertIn("mybot.plugins.points", module_names)
        self.assertIn("mybot.plugins.fortune", module_names)
        self.assertIn("mybot.plugins_disabled.slot", module_names)
        self.assertFalse(
            any(
                module_name.startswith(("plugins.", "plugins_disabled."))
                for module_name in module_names
            )
        )

    def test_daily_greetings_have_no_hardcoded_group_default(self):
        from mybot.common.config import get_daily_greet_groups

        with patch.dict(os.environ, {"DAILY_GREET_GROUPS": ""}):
            self.assertEqual(get_daily_greet_groups(), [])
