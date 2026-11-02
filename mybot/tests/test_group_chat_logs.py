from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import nonebot.message
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from mybot.common import feature_flags
from mybot.common.group_chat_logs import (
    _append_yaml_record,
    build_group_message_record,
    build_sent_group_message_record,
    extract_sent_group_message,
    get_group_log_path,
    normalize_group_message_record,
)
from mybot.plugins import group_chat_logs as group_chat_logs_plugin


def _group_event(
    message: list[dict],
    *,
    user_id: int = 654321,
    message_id: int = 1,
) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": message_id,
            "user_id": user_id,
            "group_id": 123456,
            "message": message,
            "original_message": message,
            "raw_message": "",
            "font": 0,
            "sender": {
                "user_id": user_id,
                "nickname": "太白",
                "card": "青莲居士",
                "role": "member",
            },
        }
    )


class GroupChatLogsTest(unittest.TestCase):
    def test_group_chat_logs_default_enabled(self):
        with TemporaryDirectory() as tmp_dir:
            flags_path = Path(tmp_dir) / "feature_flags.json"
            with patch.object(feature_flags, "FEATURE_FLAGS_FILE", flags_path):
                self.assertTrue(feature_flags.is_feature_enabled("group_chat_logs"))
                self.assertTrue(
                    feature_flags.is_feature_enabled("group_chat_logs", "123456")
                )

                flags_path.write_text('{"features": {"quotes": false}}', encoding="utf-8")
                self.assertTrue(feature_flags.is_feature_enabled("group_chat_logs"))

                feature_flags.set_feature_enabled("group_chat_logs", False)
                self.assertFalse(feature_flags.is_feature_enabled("group_chat_logs"))

    def test_group_log_path_uses_group_and_calendar_day(self):
        path = get_group_log_path(
            "123456",
            datetime(2026, 7, 9, 13, 14, 15),
            Path("logs"),
        )

        self.assertEqual(path, Path("logs") / "123456" / "2026" / "07" / "09.yaml")

    def test_append_yaml_record_keeps_plain_yaml_entries(self):
        record = {
            "time": "2026-07-09T13:14:15",
            "user_id": "654321",
            "nickname": "青莲居士",
            "content": [{"type": "text", "data": {"text": "举杯邀明月"}}],
        }

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "2026" / "07" / "09.yaml"
            _append_yaml_record(path, record)
            _append_yaml_record(path, record)
            text = path.read_text(encoding="utf-8")

        self.assertEqual(text.count("-\n  time:"), 2)
        self.assertIn('nickname: "青莲居士"', text)
        self.assertIn('type: "text"', text)
        self.assertIn('text: "举杯邀明月"', text)

    def test_build_record_keeps_only_four_fields_and_text(self):
        event = _group_event([{"type": "text", "data": {"text": "举杯邀明月"}}])

        record = build_group_message_record(event, datetime(2026, 7, 9, 13, 14, 15))

        self.assertEqual(
            set(record),
            {"time", "user_id", "nickname", "content"},
        )
        self.assertEqual(record["nickname"], "青莲居士")
        self.assertEqual(
            record["content"],
            [{"type": "text", "data": {"text": "举杯邀明月"}}],
        )

    def test_face_keeps_only_index_and_text(self):
        event = _group_event(
            [
                {
                    "type": "face",
                    "data": {
                        "id": "14",
                        "raw": {
                            "faceIndex": 14,
                            "faceText": "/微笑",
                            "url": "https://temporary.invalid/face",
                        },
                        "extra": "discarded",
                    },
                }
            ]
        )

        record = build_group_message_record(event)

        self.assertEqual(
            record["content"],
            [
                {
                    "type": "face",
                    "data": {"faceIndex": 14, "faceText": "/微笑"},
                }
            ],
        )

    def test_image_video_and_unknown_segments_discard_metadata(self):
        event = _group_event(
            [
                {
                    "type": "image",
                    "data": {
                        "url": "https://temporary.invalid/image",
                        "file": "cache.jpg",
                    },
                },
                {
                    "type": "video",
                    "data": {
                        "url": "https://temporary.invalid/video",
                        "file": "cache.mp4",
                    },
                },
                {"type": "custom", "data": {"secret": "discarded"}},
            ]
        )

        record = build_group_message_record(event)

        self.assertEqual(
            record["content"],
            [
                {"type": "image", "data": {"text": "图片"}},
                {"type": "video", "data": {"text": "视频"}},
                {"type": "custom", "data": {"text": "[custom]"}},
            ],
        )

    def test_mixed_message_keeps_order(self):
        event = _group_event(
            [
                {"type": "text", "data": {"text": "看"}},
                {"type": "image", "data": {"url": "https://temporary.invalid/image"}},
                {"type": "text", "data": {"text": "月亮"}},
            ]
        )

        record = build_group_message_record(event)

        self.assertEqual(
            [item["data"]["text"] for item in record["content"]],
            ["看", "图片", "月亮"],
        )

    def test_sent_record_uses_bot_identity_and_existing_segment_contract(self):
        record = build_sent_group_message_record(
            99999,
            [
                {"type": "text", "data": {"text": "看剑"}},
                {
                    "type": "image",
                    "data": {"url": "https://temporary.invalid/image"},
                },
            ],
            datetime(2026, 7, 16, 13, 14, 15),
        )

        self.assertEqual(
            record,
            {
                "time": "2026-07-16T13:14:15",
                "user_id": "99999",
                "nickname": "李太白给",
                "content": [
                    {"type": "text", "data": {"text": "看剑"}},
                    {"type": "image", "data": {"text": "图片"}},
                ],
            },
        )

    def test_plain_sent_text_becomes_one_text_segment(self):
        record = build_sent_group_message_record(99999, "举杯邀明月")

        self.assertEqual(
            record["content"],
            [{"type": "text", "data": {"text": "举杯邀明月"}}],
        )

    def test_extracts_only_normal_group_message_apis(self):
        self.assertEqual(
            extract_sent_group_message(
                "send_group_msg",
                {"group_id": 123456, "message": "明月"},
            ),
            (123456, "明月"),
        )
        self.assertEqual(
            extract_sent_group_message(
                "send_msg",
                {
                    "message_type": "group",
                    "group_id": 123456,
                    "message": "清风",
                },
            ),
            (123456, "清风"),
        )
        self.assertIsNone(
            extract_sent_group_message(
                "send_msg",
                {"message_type": "private", "user_id": 1, "message": "私语"},
            )
        )
        self.assertIsNone(
            extract_sent_group_message(
                "send_group_forward_msg",
                {"group_id": 123456, "message": "转发"},
            )
        )

    def test_old_record_is_normalized_without_migration(self):
        old_record = {
            "time": "2026-07-09T13:14:15",
            "message_id": 7,
            "group_id": "123456",
            "user_id": "654321",
            "sender": {
                "nickname": "太白",
                "card": "青莲居士",
                "role": "member",
            },
            "text": "看月亮",
            "segments": [
                {"type": "text", "data": {"text": "看"}},
                {
                    "type": "image",
                    "data": {"url": "https://temporary.invalid/image"},
                },
                {"type": "text", "data": {"text": "月亮"}},
            ],
        }

        normalized = normalize_group_message_record(old_record)

        self.assertEqual(set(normalized), {"time", "user_id", "nickname", "content"})
        self.assertEqual(normalized["nickname"], "青莲居士")
        self.assertEqual(
            [item["data"]["text"] for item in normalized["content"]],
            ["看", "图片", "月亮"],
        )


class GroupChatLogsPluginTest(unittest.IsolatedAsyncioTestCase):
    def test_inbound_collector_is_an_event_preprocessor(self):
        self.assertTrue(
            any(
                dependent.call is group_chat_logs_plugin.handle_group_chat_log
                for dependent in nonebot.message._event_preprocessors
            )
        )
        self.assertFalse(hasattr(group_chat_logs_plugin, "group_chat_log_collector"))

    async def test_normal_group_message_is_saved_before_matcher_dispatch(self):
        event = _group_event([{"type": "text", "data": {"text": "/运势"}}])
        with (
            patch.object(group_chat_logs_plugin, "is_feature_enabled", return_value=True),
            patch.object(group_chat_logs_plugin, "save_group_message_record") as save,
        ):
            await group_chat_logs_plugin.handle_group_chat_log(event)

        save.assert_called_once_with(event)

    async def test_successful_bot_group_send_is_saved_and_echo_is_not(self):
        bot = Mock(self_id="99999")
        data = {"group_id": 123456, "message": "（晃酒壶）本猫来也"}
        with (
            patch.object(group_chat_logs_plugin, "is_feature_enabled", return_value=True),
            patch.object(
                group_chat_logs_plugin,
                "save_sent_group_message_record",
            ) as save_sent,
            patch.object(
                group_chat_logs_plugin,
                "save_group_message_record",
            ) as save_incoming,
        ):
            await group_chat_logs_plugin.handle_sent_group_chat_log(
                bot,
                None,
                "send_group_msg",
                data,
                {"message_id": 88},
            )
            await group_chat_logs_plugin.handle_group_chat_log(
                _group_event(
                    [{"type": "text", "data": {"text": "（晃酒壶）本猫来也"}}],
                    user_id=99999,
                    message_id=88,
                )
            )

        save_sent.assert_called_once_with(123456, "99999", data["message"])
        save_incoming.assert_not_called()

    async def test_failed_private_and_disabled_sends_are_not_saved(self):
        bot = Mock(self_id="99999")
        with patch.object(
            group_chat_logs_plugin,
            "save_sent_group_message_record",
        ) as save:
            await group_chat_logs_plugin.handle_sent_group_chat_log(
                bot,
                RuntimeError("send failed"),
                "send_group_msg",
                {"group_id": 123456, "message": "失败"},
                None,
            )
            await group_chat_logs_plugin.handle_sent_group_chat_log(
                bot,
                None,
                "send_msg",
                {"message_type": "private", "user_id": 1, "message": "私语"},
                {"message_id": 89},
            )
            with patch.object(
                group_chat_logs_plugin,
                "is_feature_enabled",
                return_value=False,
            ):
                await group_chat_logs_plugin.handle_sent_group_chat_log(
                    bot,
                    None,
                    "send_group_msg",
                    {"group_id": 123456, "message": "已关闭"},
                    {"message_id": 90},
                )

        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
