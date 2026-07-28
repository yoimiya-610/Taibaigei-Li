from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent

import mybot.bot  # noqa: F401
from mybot.common import admin, feature_flags
from mybot.plugins import admin_console


def _group_event(role: str, user_id: int = 10001) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 1,
            "user_id": user_id,
            "group_id": 20001,
            "message": [],
            "original_message": [],
            "raw_message": "",
            "font": 0,
            "sender": {"user_id": user_id, "nickname": "tester", "role": role},
        }
    )


class GroupFeatureAdminTest(unittest.TestCase):
    def test_feature_numbers_do_not_change_with_enabled_state(self):
        features = [
            {
                "key": "quotes",
                "name": "群友语录本",
                "enabled": False,
                "protected": False,
                "aliases": [],
            },
            {
                "key": "fortune",
                "name": "签到运势",
                "enabled": True,
                "protected": False,
                "aliases": [],
            },
        ]
        with patch.object(admin_console, "collect_features", return_value=features):
            before = [item["key"] for item in admin_console._sorted_features("100")]
            features[0]["enabled"] = True
            features[1]["enabled"] = False
            after = [item["key"] for item in admin_console._sorted_features("100")]

        self.assertEqual(before, ["fortune", "quotes"])
        self.assertEqual(after, before)

    def test_feature_list_does_not_expose_system_admin_commands(self):
        rendered = admin_console._render_feature_list("100")

        self.assertNotIn("全局", rendered)
        self.assertNotIn("debug", rendered.lower())
        self.assertNotIn("debug", admin_console.COMMAND_ALIASES)
        self.assertNotIn("全局开启功能", admin_console.COMMAND_ALIASES)
        self.assertNotIn("全局关闭功能", admin_console.COMMAND_ALIASES)

    def test_group_feature_overrides_are_isolated_and_inherit_global(self):
        with TemporaryDirectory() as tmp_dir:
            flags_path = Path(tmp_dir) / "feature_flags.json"
            with patch.object(feature_flags, "FEATURE_FLAGS_FILE", flags_path):
                feature_flags.set_feature_enabled("quotes", False)
                self.assertFalse(feature_flags.is_feature_enabled("quotes", "100"))
                self.assertFalse(feature_flags.is_feature_enabled("quotes", "200"))

                feature_flags.set_feature_enabled("quotes", True, "100")
                self.assertTrue(feature_flags.is_feature_enabled("quotes", "100"))
                self.assertFalse(feature_flags.is_feature_enabled("quotes", "200"))

                feature_flags.set_feature_enabled("quotes", True)
                self.assertTrue(feature_flags.is_feature_enabled("quotes", "100"))
                self.assertTrue(feature_flags.is_feature_enabled("quotes", "200"))
                self.assertNotIn(
                    "quotes",
                    feature_flags._load_flags().get("groups", {}).get("100", {}),
                )

    def test_group_legacy_overrides_are_isolated(self):
        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                feature_flags.set_feature_enabled("legacy_slot", False, "100")
                self.assertFalse(
                    feature_flags.get_legacy_game_enabled("legacy_slot", group_id="100")
                )
                self.assertIsNone(
                    feature_flags.get_legacy_game_override("legacy_slot", group_id="200")
                )

    def test_new_day_write_does_not_revive_stale_group_overrides(self):
        with TemporaryDirectory() as tmp_dir:
            overrides_path = Path(tmp_dir) / "legacy_game_overrides.json"
            with patch.object(feature_flags, "LEGACY_GAME_OVERRIDES_FILE", overrides_path):
                with patch.object(
                    feature_flags,
                    "_coerce_day",
                    return_value=date(2026, 7, 9),
                ):
                    feature_flags.set_feature_enabled("legacy_slot", False, "100")
                with patch.object(
                    feature_flags,
                    "_coerce_day",
                    return_value=date(2026, 7, 10),
                ):
                    feature_flags.set_feature_enabled("legacy_dice", True, "200")
                    self.assertIsNone(
                        feature_flags.get_legacy_game_override(
                            "legacy_slot",
                            group_id="100",
                        )
                    )

    def test_platform_group_roles_and_system_admin_have_expected_permissions(self):
        with patch.object(admin, "get_admin_user_ids", return_value={"10003"}):
            self.assertTrue(admin.is_group_admin(_group_event("owner", 10001)))
            self.assertTrue(admin.is_group_admin(_group_event("admin", 10002)))
            self.assertTrue(admin.is_group_admin(_group_event("member", 10003)))
            self.assertFalse(admin.is_group_admin(_group_event("member", 10004)))


if __name__ == "__main__":
    unittest.main()
