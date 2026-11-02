import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common import (
    accounting,
    feature_flags,
    gift_store,
    group_management,
    poetry_society,
    streak,
)
from mybot.common.ai_client import AIChatMessage, AIToolCall
from mybot.common.ai_readonly_tools import (
    AIReadOnlyContext,
    MAX_TOOL_CALLS,
    ReadonlyToolError,
    dispatch_readonly_tool,
    extract_event_at_user_ids,
    readonly_tool_schemas,
    run_readonly_tool_conversation,
)
from mybot.common.json_store import save_json


class AIReadonlyToolTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.points_file = root / "points.json"
        self.fortune_file = root / "fortune_data.json"
        self.gift_file = root / "gift_inventory.json"
        self.poetry_file = root / "poetry_society.json"
        self.activity_file = root / "group_activities.json"
        self.feature_flags_file = root / "feature_flags.json"
        for target, attribute, value in (
            (accounting, "POINTS_FILE", self.points_file),
            (streak, "DATA_FILE", self.fortune_file),
            (gift_store, "GIFT_INVENTORY_FILE", self.gift_file),
            (poetry_society, "DATA_FILE", self.poetry_file),
            (group_management, "ACTIVITY_FILE", self.activity_file),
            (feature_flags, "FEATURE_FLAGS_FILE", self.feature_flags_file),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = datetime(2026, 7, 15, 12, 0, tzinfo=streak.APP_TIMEZONE)

    def context(self, user_id: str = "10001", group_id: str | None = "20001") -> AIReadOnlyContext:
        return AIReadOnlyContext(user_id=user_id, group_id=group_id, now=self.now)

    def test_current_sender_reads_only_current_group_state(self):
        save_json(
            self.points_file,
            {
                "20001_10001": {
                    "user_id": "10001",
                    "group_id": "20001",
                    "current": 87,
                    "total": 321,
                },
                "20002_10001": {
                    "user_id": "10001",
                    "group_id": "20002",
                    "current": 999,
                    "total": 1000,
                },
                "20001_10002": {
                    "user_id": "10002",
                    "group_id": "20001",
                    "current": 456,
                    "total": 654,
                },
            },
        )
        today = self.now.date().isoformat()
        save_json(
            self.fortune_file,
            {
                **streak.DEFAULT_FORTUNE_DATA,
                "fortune_record": {
                    streak.fortune_record_key(today, "10001", "20001"): {"fortune": "吉"},
                    streak.fortune_record_key(today, "10001", "20002"): {"fortune": "大吉"},
                },
            },
        )
        save_json(
            self.gift_file,
            {
                "inventories": {
                    "20001_10001": {
                        "user_id": "10001",
                        "group_id": "20001",
                        "items": {"milk_tea": 2},
                    },
                    "20002_10001": {
                        "user_id": "10001",
                        "group_id": "20002",
                        "items": {"crown": 9},
                    },
                }
            },
        )

        points = dispatch_readonly_tool("get_my_points", "{}", self.context())
        checkin = dispatch_readonly_tool("get_my_checkin_status", "{}", self.context())
        inventory = dispatch_readonly_tool("get_my_gift_inventory", "{}", self.context())

        self.assertEqual(points["current_points"], 87)
        self.assertEqual(points["total_earned_points"], 321)
        self.assertTrue(checkin["signed_today"])
        self.assertEqual(inventory["total_items"], 2)
        self.assertEqual(inventory["items"][0]["name"], "云顶奶茶")

        other_group = dispatch_readonly_tool("get_my_points", "{}", self.context(group_id="20002"))
        self.assertEqual(other_group["current_points"], 999)

    def test_missing_state_and_empty_inventory_do_not_create_files(self):
        points = dispatch_readonly_tool("get_my_points", "{}", self.context())
        checkin = dispatch_readonly_tool("get_my_checkin_status", "{}", self.context())
        inventory = dispatch_readonly_tool("get_my_gift_inventory", "{}", self.context())
        society = dispatch_readonly_tool("get_current_poetry_society", "{}", self.context())
        activity = dispatch_readonly_tool("get_current_group_activity", "{}", self.context())

        self.assertEqual(points["current_points"], 0)
        self.assertFalse(checkin["signed_today"])
        self.assertTrue(inventory["empty"])
        self.assertTrue(society["theme"])
        self.assertEqual(society["phase"], "open")
        self.assertFalse(activity["has_activity"])
        self.assertEqual(activity["remaining_text"], "未设活动")
        self.assertFalse(self.points_file.exists())
        self.assertFalse(self.fortune_file.exists())
        self.assertFalse(self.gift_file.exists())
        self.assertFalse(self.poetry_file.exists())
        self.assertFalse(self.activity_file.exists())

    def test_poetry_snapshot_does_not_persist_default_group_or_week(self):
        original = {"schema_version": 1, "groups": {}}
        save_json(self.poetry_file, original)
        before = self.poetry_file.read_text(encoding="utf-8")

        result = poetry_society.get_overview_snapshot("20001", self.now)

        self.assertTrue(result["week"]["theme"])
        self.assertEqual(self.poetry_file.read_text(encoding="utf-8"), before)
        self.assertEqual(json.loads(before), original)

    def test_model_cannot_override_identity_or_scope(self):
        save_json(
            self.points_file,
            {
                "20001_10001": {"current": 7, "total": 8},
                "20001_10002": {"current": 700, "total": 800},
                "20002_10001": {"current": 900, "total": 1000},
            },
        )
        for arguments in (
            '{"user_id":"10002"}',
            '{"group_id":"20002"}',
            '{"path":"points.json"}',
            '{"url":"https://example.com"}',
            '{"sql":"select *"}',
            '[]',
            '{broken',
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ReadonlyToolError, "invalid_arguments"):
                    dispatch_readonly_tool("get_my_points", arguments, self.context())

        result = dispatch_readonly_tool("get_my_points", "{}", self.context())
        self.assertEqual(result["current_points"], 7)

    def test_schemas_are_parameterless_and_allowlisted(self):
        schemas = readonly_tool_schemas(self.context())
        self.assertEqual(
            {schema["function"]["name"] for schema in schemas},
            {
                "get_my_points",
                "get_my_checkin_status",
                "get_my_gift_inventory",
                "get_current_poetry_society",
                "get_current_group_activity",
            },
        )
        for schema in schemas:
            parameters = schema["function"]["parameters"]
            self.assertEqual(parameters["properties"], {})
            self.assertFalse(parameters["additionalProperties"])

    def test_disabled_feature_is_not_published_and_cannot_be_called_directly(self):
        feature_flags.set_feature_enabled("points", False, "20001")
        self.points_file.write_text("{broken", encoding="utf-8")

        published_names = {
            schema["function"]["name"]
            for schema in readonly_tool_schemas(self.context())
        }
        self.assertNotIn("get_my_points", published_names)
        self.assertIn("get_my_checkin_status", published_names)
        with self.assertRaisesRegex(ReadonlyToolError, "feature_disabled"):
            dispatch_readonly_tool("get_my_points", "{}", self.context())

    def test_disabled_group_activity_is_hidden_and_direct_call_is_rejected(self):
        feature_flags.set_feature_enabled("group_admin_assistant", False, "20001")
        published_names = {
            schema["function"]["name"]
            for schema in readonly_tool_schemas(self.context())
        }

        self.assertNotIn("get_current_group_activity", published_names)
        with self.assertRaisesRegex(ReadonlyToolError, "feature_disabled"):
            dispatch_readonly_tool("get_current_group_activity", "{}", self.context())

    def test_group_activity_returns_public_summary_with_group_isolation(self):
        save_json(
            self.activity_file,
            {
                "version": 1,
                "groups": {
                    "20001": {
                        "current": {
                            "id": "private-id-1",
                            "name": "春日雅集",
                            "creator_id": "90001",
                            "status": "active",
                            "participants": {"10001": "甲", "10002": "乙"},
                            "chain": [
                                {"user_id": "10001", "nickname": "甲", "content": "不可泄露正文"}
                            ],
                            "deadline": "2026-07-15T13:30:00",
                        }
                    },
                    "20002": {
                        "current": {
                            "id": "private-id-2",
                            "name": "邻群夜游",
                            "creator_id": "90002",
                            "status": "active",
                            "participants": {"20002": "丙"},
                            "chain": [],
                            "deadline": "",
                        }
                    },
                },
            },
        )

        current = dispatch_readonly_tool("get_current_group_activity", "{}", self.context())
        other = dispatch_readonly_tool(
            "get_current_group_activity",
            "{}",
            self.context(group_id="20002"),
        )

        self.assertEqual(current["activity_name"], "春日雅集")
        self.assertEqual(current["participant_count"], 2)
        self.assertEqual(current["chain_entry_count"], 1)
        self.assertEqual(current["deadline_status"], "scheduled")
        self.assertEqual(current["remaining_seconds"], 5400)
        self.assertEqual(current["remaining_text"], "1小时30分钟")
        self.assertEqual(other["activity_name"], "邻群夜游")
        self.assertFalse(other["has_deadline"])
        self.assertEqual(other["remaining_text"], "未设截止")
        serialized = json.dumps(current, ensure_ascii=False)
        for sensitive in ("private-id-1", "90001", "10001", "甲", "不可泄露正文"):
            self.assertNotIn(sensitive, serialized)

    def test_group_activity_expired_deadline_is_normalized_without_mutation(self):
        original = {
            "version": 1,
            "groups": {
                "20001": {
                    "current": {
                        "name": "午前小聚",
                        "status": "active",
                        "participants": {},
                        "chain": [],
                        "deadline": "2026-07-15T11:00:00",
                    }
                }
            },
        }
        save_json(self.activity_file, original)
        before = self.activity_file.read_text(encoding="utf-8")

        result = dispatch_readonly_tool("get_current_group_activity", "{}", self.context())

        self.assertTrue(result["deadline_reached"])
        self.assertEqual(result["deadline_status"], "reached")
        self.assertEqual(result["remaining_seconds"], 0)
        self.assertEqual(result["remaining_text"], "已到截止时刻")
        self.assertEqual(result["deadline_at"], "2026-07-15T11:00:00+08:00")
        self.assertEqual(self.activity_file.read_text(encoding="utf-8"), before)

    def test_private_scope_publishes_no_group_tools(self):
        self.assertEqual(readonly_tool_schemas(self.context(group_id=None)), [])

    def test_unknown_tool_and_private_scope_are_rejected(self):
        with self.assertRaisesRegex(ReadonlyToolError, "unknown_tool"):
            dispatch_readonly_tool("read_any_file", "{}", self.context())
        with self.assertRaisesRegex(ReadonlyToolError, "group_scope_required"):
            dispatch_readonly_tool("get_my_points", "{}", self.context(group_id=None))

    def test_only_real_at_segments_are_kept_as_trusted_context(self):
        message = Message(
            [
                MessageSegment.text("昵称甲 123456"),
                MessageSegment.at(30001),
                MessageSegment.at(99999),
                MessageSegment.at(30001),
                MessageSegment.at("all"),
            ]
        )
        event = SimpleNamespace(self_id=99999, get_message=lambda: message)

        self.assertEqual(extract_event_at_user_ids(event), ("30001",))

    def test_tool_transcript_preserves_assistant_call_and_tool_call_id(self):
        first = AIChatMessage(
            content=None,
            reasoning_content="需要查当前提问者的积分",
            tool_calls=(AIToolCall("call_points", "get_my_points", "{}"),),
        )
        second = AIChatMessage(content="（翻开账页）你在本群现有 0 积分。")
        mock_completion = AsyncMock(side_effect=[first, second])
        messages = [{"role": "user", "content": "我还有多少积分"}]

        with patch(
            "mybot.common.ai_readonly_tools.chat_completion_message",
            mock_completion,
        ):
            reply = asyncio.run(run_readonly_tool_conversation(messages, self.context()))

        self.assertIn("0 积分", reply)
        self.assertEqual(mock_completion.await_count, 2)
        second_messages = mock_completion.await_args_list[1].args[0]
        self.assertEqual(second_messages[-2], first.to_api_dict())
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "call_points")
        self.assertEqual(json.loads(second_messages[-1]["content"])["current_points"], 0)
        self.assertEqual(messages, [{"role": "user", "content": "我还有多少积分"}])

    def test_plain_reply_needs_no_tool_and_keeps_existing_conversation_shape(self):
        mock_completion = AsyncMock(return_value=AIChatMessage(content="普通回答"))
        messages = [{"role": "user", "content": "陪我聊聊天"}]

        with patch(
            "mybot.common.ai_readonly_tools.chat_completion_message",
            mock_completion,
        ):
            reply = asyncio.run(run_readonly_tool_conversation(messages, self.context()))

        self.assertEqual(reply, "普通回答")
        self.assertEqual(mock_completion.await_count, 1)
        self.assertEqual(messages, [{"role": "user", "content": "陪我聊聊天"}])

    def test_total_tool_call_limit_rejects_before_dispatch(self):
        calls = tuple(
            AIToolCall(f"call_{index}", "get_my_points", "{}")
            for index in range(MAX_TOOL_CALLS + 1)
        )
        mock_completion = AsyncMock(return_value=AIChatMessage(content=None, tool_calls=calls))

        with patch(
            "mybot.common.ai_readonly_tools.chat_completion_message",
            mock_completion,
        ):
            with self.assertRaisesRegex(ReadonlyToolError, "tool_call_limit"):
                asyncio.run(run_readonly_tool_conversation([], self.context()))

        self.assertFalse(self.points_file.exists())

    def test_tool_round_limit_forces_a_final_no_tool_turn(self):
        first = AIChatMessage(
            content=None,
            tool_calls=(AIToolCall("call_1", "get_my_points", "{}"),),
        )
        invalid_second = AIChatMessage(
            content=None,
            tool_calls=(AIToolCall("call_2", "get_my_points", "{}"),),
        )
        mock_completion = AsyncMock(side_effect=[first, invalid_second])

        with patch(
            "mybot.common.ai_readonly_tools.chat_completion_message",
            mock_completion,
        ):
            with self.assertRaisesRegex(ReadonlyToolError, "tool_round_limit"):
                asyncio.run(
                    run_readonly_tool_conversation(
                        [],
                        self.context(),
                        max_tool_rounds=1,
                    )
                )

        self.assertEqual(mock_completion.await_args_list[0].kwargs["tool_choice"], "auto")
        self.assertEqual(mock_completion.await_args_list[1].kwargs["tool_choice"], "none")


if __name__ == "__main__":
    unittest.main()
