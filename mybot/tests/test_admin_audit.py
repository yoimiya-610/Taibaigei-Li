from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent

import mybot.bot  # noqa: F401
from mybot.common.admin_audit import get_admin_audit_records, record_admin_action
from mybot.common.json_store import JsonStoreReadError
from mybot.plugins import admin_console


def _group_event(user_id: int, group_id: int) -> GroupMessageEvent:
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
            "sender": {"user_id": user_id, "nickname": "tester", "role": "member"},
        }
    )


class AdminAuditTest(unittest.TestCase):
    def test_admin_console_forwards_source_and_target_context_to_audit_store(self):
        event = _group_event(10001, 20001)
        with patch.object(admin_console, "record_admin_action") as mocked:
            suffix = admin_console._audit_action(
                event,
                action="feature_toggle",
                scope="group",
                target_group_id="20002",
                details={"feature_key": "poetry_society", "after": True},
            )

        self.assertEqual(suffix, "")
        mocked.assert_called_once_with(
            actor_user_id="10001",
            action="feature_toggle",
            scope="group",
            source_group_id="20001",
            target_group_id="20002",
            target_user_id=None,
            details={"feature_key": "poetry_society", "after": True},
        )

    def test_records_actor_scope_targets_and_cross_group_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "admin_audit.json"
            record = record_admin_action(
                actor_user_id="10001",
                action="feature_toggle",
                scope="group",
                source_group_id="20001",
                target_group_id="20002",
                details={
                    "command": "开启功能",
                    "feature_key": "poetry_society",
                    "before": False,
                    "after": True,
                    "secret": "must-not-be-recorded",
                },
                store_path=path,
                now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
            )

            self.assertTrue(record["cross_group"])
            self.assertEqual(record["actor_user_id"], "10001")
            self.assertEqual(record["target_group_id"], "20002")
            self.assertNotIn("secret", record["details"])
            self.assertEqual(get_admin_audit_records(store_path=path), [record])

    def test_retention_is_bounded_and_counts_rotated_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "admin_audit.json"
            with patch("mybot.common.admin_audit.MAX_RETAINED_AUDIT_RECORDS", 2):
                for index in range(3):
                    record_admin_action(
                        actor_user_id="10001",
                        action=f"action_{index}",
                        scope="system",
                        store_path=path,
                    )

            records = get_admin_audit_records(store_path=path)
            self.assertEqual([item["action"] for item in records], ["action_1", "action_2"])
            text = path.read_text(encoding="utf-8")
            self.assertIn('"dropped_records": 1', text)
            self.assertEqual(get_admin_audit_records(limit=0, store_path=path), [])

    def test_corrupt_audit_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "admin_audit.json"
            original = b'{"records": ['
            path.write_bytes(original)

            with self.assertRaises(JsonStoreReadError):
                record_admin_action(
                    actor_user_id="10001",
                    action="feature_toggle",
                    scope="group",
                    target_group_id="20001",
                    store_path=path,
                )
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
