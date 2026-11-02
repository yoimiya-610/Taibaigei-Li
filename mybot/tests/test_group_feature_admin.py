from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

import mybot.bot  # noqa: F401
from mybot.common import admin, feature_flags
from mybot.plugins import admin_console, fortune


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


def _private_event(user_id: int = 10001) -> PrivateMessageEvent:
    return PrivateMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": 1,
            "user_id": user_id,
            "message": [],
            "original_message": [],
            "raw_message": "",
            "font": 0,
            "sender": {"user_id": user_id, "nickname": "tester"},
        }
    )


class GroupFeatureAdminTest(unittest.TestCase):
    def test_feature_toggle_parser_accepts_optional_group_id(self):
        self.assertEqual(
            admin_console._parse_feature_toggle_args("群聊记录"),
            ("群聊记录", None),
        )
        self.assertEqual(
            admin_console._parse_feature_toggle_args("群聊记录 30001"),
            ("群聊记录", "30001"),
        )
        for invalid in ("", "群聊记录 0", "群聊记录 30001 多余"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    admin_console._parse_feature_toggle_args(invalid)

    def test_only_system_admin_can_target_an_explicit_group(self):
        group_admin = _group_event("member", 10002)
        system_admin = _group_event("member", 10003)
        private_system_admin = _private_event(10003)

        with patch.object(
            admin_console,
            "is_admin_user",
            side_effect=lambda user_id: user_id == "10003",
        ):
            self.assertEqual(
                admin_console._resolve_group_command_target(system_admin, "30001"),
                "30001",
            )
            self.assertEqual(
                admin_console._resolve_group_command_target(
                    private_system_admin,
                    "30001",
                ),
                "30001",
            )
            self.assertEqual(
                admin_console._resolve_group_command_target(group_admin, None),
                "20001",
            )
            with self.assertRaises(PermissionError):
                admin_console._resolve_group_command_target(group_admin, "30001")

    def test_debug_fortune_accepts_current_or_explicit_group(self):
        self.assertEqual(
            fortune._resolve_debug_fortune_group(_group_event("member"), ""),
            "20001",
        )
        self.assertEqual(
            fortune._resolve_debug_fortune_group(_private_event(), "30001"),
            "30001",
        )
        self.assertIsNone(fortune._resolve_debug_fortune_group(_private_event(), ""))
        self.assertIsNone(
            fortune._resolve_debug_fortune_group(
                _group_event("member"),
                "not-a-group",
            )
        )

    def test_feature_numbers_do_not_change_with_enabled_state(self):
        features = [
            {
                "key": "quotes",
                "name": "群友语录本",
                "enabled": False,
                "protected": False,
                "aliases": [],
                "public": True,
            },
            {
                "key": "fortune",
                "name": "签到运势",
                "enabled": True,
                "protected": False,
                "aliases": [],
                "public": True,
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

    def test_group_admin_only_sees_and_resolves_public_features(self):
        public_features = admin_console._sorted_features("100", public_only=True)
        public_keys = {item["key"] for item in public_features}

        self.assertIn("quotes", public_keys)
        self.assertNotIn("blacklist", public_keys)
        self.assertNotIn("rate_limit", public_keys)
        self.assertNotIn("group_chat_logs", public_keys)
        self.assertNotIn("黑名单", admin_console._render_feature_list("100", public_only=True))
        self.assertNotIn("频率限制", admin_console._render_feature_list("100", public_only=True))
        self.assertNotIn("群聊记录", admin_console._render_feature_list("100", public_only=True))
        self.assertIsNone(
            admin_console._resolve_feature_target("blacklist", "100", public_only=True)
        )
        self.assertIsNone(
            admin_console._resolve_feature_target("群聊记录", "100", public_only=True)
        )

    def test_system_admin_keeps_full_feature_access(self):
        full_features = admin_console._sorted_features("100")
        full_keys = {item["key"] for item in full_features}

        self.assertIn("blacklist", full_keys)
        self.assertIn("rate_limit", full_keys)
        self.assertIn("group_chat_logs", full_keys)
        self.assertEqual(
            admin_console._resolve_feature_target("群聊记录", "100"),
            "group_chat_logs",
        )

    def test_feature_visibility_follows_system_admin_identity(self):
        group_admin = _group_event("admin", 10002)
        system_admin = _group_event("member", 10003)

        with patch.object(
            admin_console,
            "is_admin_user",
            side_effect=lambda user_id: user_id == "10003",
        ):
            self.assertTrue(admin_console._public_features_only(group_admin))
            self.assertFalse(admin_console._public_features_only(system_admin))

    def test_number_resolution_uses_callers_visible_list(self):
        public_features = admin_console._sorted_features("100", public_only=True)
        full_features = admin_console._sorted_features("100")
        public_index = next(
            index
            for index, item in enumerate(public_features, start=1)
            if item["key"] == "quotes"
        )
        full_index = next(
            index
            for index, item in enumerate(full_features, start=1)
            if item["key"] == "quotes"
        )

        self.assertEqual(
            admin_console._resolve_feature_target(
                str(public_index),
                "100",
                public_only=True,
            ),
            "quotes",
        )
        self.assertEqual(
            admin_console._resolve_feature_target(str(full_index), "100"),
            "quotes",
        )

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

    def test_new_day_write_preserves_existing_group_overrides(self):
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
                    self.assertFalse(
                        feature_flags.get_legacy_game_override(
                            "legacy_slot", group_id="100"
                        )
                    )

    def test_platform_group_roles_do_not_grant_robot_permissions(self):
        with patch.object(admin, "get_admin_user_ids", return_value={"10003"}):
            self.assertFalse(admin.is_group_admin(_group_event("owner", 10001)))
            self.assertFalse(admin.is_group_admin(_group_event("admin", 10002)))
            self.assertTrue(admin.is_group_admin(_group_event("member", 10003)))
            self.assertFalse(admin.is_group_admin(_group_event("member", 10004)))


if __name__ == "__main__":
    unittest.main()
