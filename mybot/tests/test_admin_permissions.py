import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent

import mybot.bot  # noqa: F401
from mybot.common import admin
from mybot.common import help_registry
from mybot.plugins import admin_console


def _group_event(role: str, user_id: int, group_id: int) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "sub_type": "normal",
            "user_id": user_id,
            "message_type": "group",
            "message_id": 1,
            "message": [],
            "original_message": [],
            "raw_message": "",
            "font": 0,
            "group_id": group_id,
            "sender": {"user_id": user_id, "nickname": "tester", "role": role},
        }
    )


class AdminPermissionsTest(unittest.TestCase):
    def test_permission_matrix_has_all_five_levels(self):
        self.assertEqual(set(admin.PERMISSION_LEVEL_NAMES), {1, 2, 3, 4, 5})
        self.assertEqual(admin.get_feature_permission_level("poem"), 2)
        self.assertEqual(admin.get_feature_permission_level("ai_chat"), 3)
        self.assertEqual(admin.get_feature_permission_level("legacy_slot"), 4)
        self.assertEqual(admin.get_feature_permission_level("group_chat_logs"), 5)
        self.assertEqual(admin.get_feature_permission_level("image_library"), 5)
        self.assertIsNone(admin.get_feature_permission_level("backup"))

    def test_group_permissions_are_isolated_and_can_be_revoked(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "admin_permissions.json"
            with (
                patch.object(admin, "ADMIN_PERMISSIONS_FILE", path),
                patch.object(admin, "get_admin_user_ids", return_value=set()),
            ):
                admin.set_group_permission_level("20001", "10001", 3)
                self.assertEqual(admin.get_group_permission_level("20001", "10001"), 3)
                self.assertEqual(admin.get_group_permission_level("20002", "10001"), 0)
                admin.set_group_permission_level("20001", "10001", 0)
                self.assertEqual(admin.get_group_permission_level("20001", "10001"), 0)
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data, {"version": 1, "groups": {}})

    def test_onebot_roles_never_grant_permissions(self):
        with patch.object(admin, "get_admin_user_ids", return_value=set()):
            for role in ("owner", "admin", "member"):
                event = _group_event(role, 10001, 20001)
                with patch.object(
                    admin,
                    "ADMIN_PERMISSIONS_FILE",
                    Path("missing-admin-permissions.json"),
                ):
                    self.assertEqual(admin.get_event_permission_level(event), 0)
                    self.assertFalse(admin.is_group_admin(event))

    def test_system_admins_come_from_environment_only(self):
        with patch.dict(
            os.environ,
            {"BOT_ADMINS": "10001", "SUPERUSERS": '["10002"]'},
            clear=False,
        ):
            self.assertEqual(admin.get_admin_user_ids(), {"10001", "10002"})

    def test_system_admin_cannot_be_overridden_in_group_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "admin_permissions.json"
            with (
                patch.object(admin, "ADMIN_PERMISSIONS_FILE", path),
                patch.object(admin, "get_admin_user_ids", return_value={"10001"}),
            ):
                with self.assertRaisesRegex(ValueError, "system_admin_immutable"):
                    admin.set_group_permission_level("20001", "10001", 0)
                self.assertFalse(path.exists())

    def test_legacy_direct_shape_is_read_and_migrated_on_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "admin_permissions.json"
            path.write_text(
                json.dumps({"20001": {"10001": {"level": 2}}}),
                encoding="utf-8",
            )
            with (
                patch.object(admin, "ADMIN_PERMISSIONS_FILE", path),
                patch.object(admin, "get_admin_user_ids", return_value=set()),
            ):
                self.assertEqual(admin.get_group_permission_level("20001", "10001"), 2)
                admin.set_group_permission_level("20001", "10002", 4)
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["version"], 1)
                self.assertEqual(data["groups"]["20001"]["10001"], {"level": 2})
                self.assertEqual(data["groups"]["20001"]["10002"], 4)

    def test_admin_command_arguments_are_strict(self):
        self.assertEqual(
            admin_console._parse_admin_args("20001 10001 5"),
            ("20001", "10001", 5),
        )
        self.assertEqual(
            admin_console._parse_admin_args("20001 10001"),
            ("20001", "10001", None),
        )
        for invalid in (
            "",
            "20001",
            "20001 nickname 3",
            "group 10001 3",
            "20001 10001 -1",
            "20001 10001 6",
            "20001 10001 3 extra",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    admin_console._parse_admin_args(invalid)

    def test_feature_visibility_follows_matrix_and_group_scope(self):
        event = _group_event("owner", 10001, 20001)
        with (
            patch.object(admin_console, "is_admin_user", return_value=False),
            patch.object(admin_console, "get_event_permission_level", return_value=3),
        ):
            self.assertTrue(
                admin_console._feature_visible_to_event(
                    event, {"key": "poem", "public": True}
                )
            )
            self.assertTrue(
                admin_console._feature_visible_to_event(
                    event, {"key": "ai_chat", "public": True}
                )
            )
            self.assertFalse(
                admin_console._feature_visible_to_event(
                    event, {"key": "legacy_slot", "public": True}
                )
            )
            self.assertFalse(
                admin_console._feature_visible_to_event(
                    event, {"key": "group_chat_logs", "public": False}
                )
            )

    def test_help_is_the_same_public_view_for_every_identity(self):
        ordinary_help = help_registry.render_help_menu("20001", "10001")
        group_admin_help = help_registry.render_help_menu("20001", "10002")
        system_admin_help = help_registry.render_help_menu("20002", "10003")
        private_help = help_registry.render_help_menu(None, "10003")
        self.assertEqual(
            {ordinary_help, group_admin_help, system_admin_help, private_help},
            {ordinary_help},
        )
        self.assertNotIn("/功能列表", ordinary_help)
        self.assertNotIn("/管理员", ordinary_help)
        self.assertIn("/群管理介绍", ordinary_help)

    def test_group_management_is_nested_under_system_information(self):
        self.assertNotIn("群聊管理", help_registry.CATEGORY_META)
        system_help = help_registry.render_category_help("系统说明")
        self.assertIsNotNone(system_help)
        self.assertIn("/群管理介绍", system_help)


if __name__ == "__main__":
    unittest.main()
