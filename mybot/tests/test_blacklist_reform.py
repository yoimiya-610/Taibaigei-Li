import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

import mybot.bot  # noqa: F401
from mybot.plugins import blacklist


def _group_event(message: str, group_id: int = 20001) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 1,
            "user_id": 10001,
            "group_id": group_id,
            "message": [{"type": "text", "data": {"text": message}}],
            "original_message": [{"type": "text", "data": {"text": message}}],
            "raw_message": message,
            "font": 0,
            "sender": {"user_id": 10001, "nickname": "tester", "role": "member"},
        }
    )


def _private_event(message: str) -> PrivateMessageEvent:
    return PrivateMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": 1,
            "user_id": 10001,
            "message": [{"type": "text", "data": {"text": message}}],
            "original_message": [{"type": "text", "data": {"text": message}}],
            "raw_message": message,
            "font": 0,
            "sender": {"user_id": 10001, "nickname": "tester"},
        }
    )


class BlacklistReformTest(unittest.TestCase):
    def test_existing_words_are_inherited_as_system_defaults(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "blacklist.json"
            legacy_path = Path(tmp_dir) / "legacy" / "blacklist.json"
            with (
                patch.object(blacklist, "BLACKLIST_FILE", path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                self.assertEqual(blacklist.get_system_blacklist(), blacklist.BLACKLIST_WORDS)
                self.assertFalse(path.exists())

    def test_system_blacklist_applies_globally(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "blacklist.json"
            legacy_path = Path(tmp_dir) / "legacy" / "blacklist.json"
            with (
                patch.object(blacklist, "BLACKLIST_FILE", path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                blacklist.toggle_system_blacklist("GlobalWord")
                self.assertTrue(blacklist.check_blacklist(_group_event("globalword")))
                self.assertTrue(blacklist.check_blacklist(_private_event("GLOBALWORD")))

    def test_group_blacklists_are_isolated(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "blacklist.json"
            legacy_path = Path(tmp_dir) / "legacy" / "blacklist.json"
            with (
                patch.object(blacklist, "BLACKLIST_FILE", path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                self.assertTrue(blacklist.toggle_group_blacklist("20001", "LocalWord"))
                self.assertTrue(blacklist.check_blacklist(_group_event("localword", 20001)))
                self.assertFalse(blacklist.check_blacklist(_group_event("localword", 20002)))
                self.assertFalse(blacklist.check_blacklist(_private_event("localword")))

    def test_toggle_is_case_insensitive_and_preserves_other_scopes(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "blacklist.json"
            legacy_path = Path(tmp_dir) / "legacy" / "blacklist.json"
            with (
                patch.object(blacklist, "BLACKLIST_FILE", path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                blacklist.toggle_system_blacklist("SystemNew")
                blacklist.toggle_group_blacklist("20001", "GroupNew")
                self.assertFalse(blacklist.toggle_group_blacklist("20001", "groupnew"))
                self.assertIn("SystemNew", blacklist.get_system_blacklist())
                self.assertEqual(blacklist.get_group_blacklist("20001"), [])

    def test_commands_do_not_trigger_content_filter(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "blacklist.json"
            legacy_path = Path(tmp_dir) / "legacy" / "blacklist.json"
            with (
                patch.object(blacklist, "BLACKLIST_FILE", path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                blacklist.toggle_system_blacklist("SecretWord")
                self.assertFalse(
                    blacklist.check_blacklist(_group_event("/系统黑名单 SecretWord"))
                )

    def test_canonical_path_is_source_relative_under_both_startup_directories(self):
        project_root = Path(__file__).resolve().parents[2]
        expected = project_root / "mybot" / "data" / "blacklist.json"
        original_cwd = Path.cwd()
        try:
            os.chdir(project_root)
            from_repo_root = blacklist.BLACKLIST_FILE.resolve()
            os.chdir(project_root / "mybot")
            from_bot_root = blacklist.BLACKLIST_FILE.resolve()
        finally:
            os.chdir(original_cwd)

        self.assertEqual(from_repo_root, expected.resolve())
        self.assertEqual(from_bot_root, expected.resolve())

    def test_legacy_nested_path_is_used_in_place_without_copy_or_delete(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            canonical_path = root / "mybot" / "data" / "blacklist.json"
            legacy_path = root / "mybot" / "mybot" / "data" / "blacklist.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps(
                    {"system": ["LegacyWord"], "groups": {"20001": ["GroupWord"]}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(blacklist, "BLACKLIST_FILE", canonical_path),
                patch.object(blacklist, "LEGACY_BLACKLIST_FILE", legacy_path),
            ):
                self.assertEqual(blacklist.get_system_blacklist(), ["LegacyWord"])
                self.assertTrue(blacklist.toggle_group_blacklist("20001", "AnotherWord"))

            self.assertFalse(canonical_path.exists())
            self.assertTrue(legacy_path.exists())
            stored = json.loads(legacy_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["system"], ["LegacyWord"])
            self.assertEqual(stored["groups"]["20001"], ["GroupWord", "AnotherWord"])

    def test_platform_roles_do_not_grant_blacklist_permissions(self):
        owner = _group_event("")
        owner.sender.role = "owner"
        group_admin = _group_event("")
        group_admin.sender.role = "admin"
        member = _group_event("")
        with patch.object(blacklist, "has_command_permission", return_value=False):
            self.assertFalse(blacklist.has_command_permission(owner, "group_blacklist"))
            self.assertFalse(blacklist.has_command_permission(group_admin, "group_blacklist"))
            self.assertFalse(blacklist.has_command_permission(member, "group_blacklist"))
        with patch.object(blacklist, "is_admin_user", return_value=True):
            self.assertTrue(blacklist.is_admin_user(member.get_user_id()))


if __name__ == "__main__":
    unittest.main()
