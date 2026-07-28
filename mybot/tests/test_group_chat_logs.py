from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common.feature_flags import is_feature_enabled
from mybot.common.group_chat_logs import (
    _append_yaml_record,
    get_group_log_path,
)


class GroupChatLogsTest(unittest.TestCase):
    def test_group_chat_logs_default_enabled(self):
        self.assertTrue(is_feature_enabled("group_chat_logs"))

    def test_group_log_path_uses_group_and_calendar_day(self):
        path = get_group_log_path(
            "123456",
            datetime(2026, 7, 9, 13, 14, 15),
            Path("logs"),
        )

        self.assertEqual(path, Path("logs") / "123456" / "2026" / "07" / "09.yaml")

    def test_append_yaml_record_keeps_plain_yaml_entries(self):
        message = Message([MessageSegment.text("举杯邀明月")])
        record = {
            "time": "2026-07-09T13:14:15",
            "group_id": "123456",
            "user_id": "654321",
            "text": "举杯邀明月",
            "segments": [
                {
                    "type": segment.type,
                    "data": dict(segment.data),
                }
                for segment in message
            ],
        }

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "2026" / "07" / "09.yaml"
            _append_yaml_record(path, record)
            _append_yaml_record(path, record)
            text = path.read_text(encoding="utf-8")

        self.assertEqual(text.count("-\n  time:"), 2)
        self.assertIn('group_id: "123456"', text)
        self.assertIn('text: "举杯邀明月"', text)
        self.assertIn('type: "text"', text)


if __name__ == "__main__":
    unittest.main()
