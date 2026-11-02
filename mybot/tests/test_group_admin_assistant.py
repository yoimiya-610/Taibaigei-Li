import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException

import mybot.bot  # noqa: F401
from mybot.common import group_management as gm
from mybot.common.message_utils import get_reply_message_id
from mybot.plugins import group_admin_assistant as assistant


def _event(
    user_id: int = 10001,
    message=None,
    original_message=None,
    reply=None,
) -> GroupMessageEvent:
    message = message if message is not None else Message("/活动")
    original_message = original_message if original_message is not None else message
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "sub_type": "normal",
            "user_id": user_id,
            "message_type": "group",
            "message_id": 1,
            "message": message,
            "original_message": original_message,
            "raw_message": "/活动",
            "font": 0,
            "group_id": 20001,
            "sender": {"user_id": user_id, "nickname": "群友", "role": "member"},
            "reply": reply,
        }
    )


class ReplyParsingTest(unittest.TestCase):
    def test_activity_status_is_rendered_for_users(self):
        self.assertEqual(assistant._activity_status_text("active"), "进行中")
        self.assertEqual(assistant._activity_status_text("finished"), "已截止")
        self.assertEqual(assistant._activity_status_text("cancelled"), "已取消")
        self.assertNotIn("unknown", assistant._activity_status_text("unknown"))

    def test_reply_survives_command_parser_message_rewrite(self):
        event = _event(message=Message("/加精"))
        object.__setattr__(
            event,
            "original_message",
            Message(
                [
                    MessageSegment.text("/加精"),
                    MessageSegment("reply", {"id": 7788}),
                ]
            ),
        )
        self.assertEqual(get_reply_message_id(event), "7788")

    def test_reply_metadata_and_missing_reply(self):
        event = _event()
        object.__setattr__(event, "reply", SimpleNamespace(message_id=7788))
        self.assertEqual(get_reply_message_id(event), "7788")
        self.assertIsNone(get_reply_message_id(_event()))


class GroupAdminAssistantTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(gm, "CARD_FILE", root / "cards.json"),
            patch.object(gm, "CARD_QUEUE_FILE", root / "card_queue.json"),
            patch.object(gm, "ACTIVITY_FILE", root / "activities.json"),
            patch.object(assistant, "authorize_card", gm.authorize_card),
            patch.object(assistant, "get_card_record", gm.get_card_record),
            patch.object(assistant, "remove_card_job", gm.remove_card_job),
            patch.object(assistant, "create_activity", gm.create_activity),
            patch.object(assistant, "get_activity", gm.get_activity),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_card_sync_persists_authorization_only_after_success(self):
        bot = AsyncMock()
        bot.self_id = 99999
        bot.call_api = AsyncMock(
            side_effect=[
                {"nickname": "群友", "card": "旧名片"},
                {"role": "admin"},
                {},
            ]
        )
        matcher = AsyncMock()
        matcher.finish = AsyncMock(side_effect=FinishedException)
        with patch.object(
            assistant,
            "get_display_title",
            return_value={"title": "诗客"},
        ):
            with self.assertRaises(FinishedException):
                await assistant._authorize_and_apply(
                    matcher, bot, _event(), "【称号】昵称"
                )
        self.assertTrue(gm.get_card_record("20001", "10001")["enabled"])
        self.assertEqual(
            bot.call_api.await_args_list[-1].kwargs,
            {"group_id": 20001, "user_id": 10001, "card": "诗客群友"},
        )

    async def test_card_sync_failure_does_not_create_authorization(self):
        bot = AsyncMock()
        bot.self_id = 99999
        bot.call_api = AsyncMock(
            side_effect=[
                {"nickname": "群友", "card": "旧名片"},
                {"role": "member"},
            ]
        )
        matcher = AsyncMock()
        matcher.finish = AsyncMock(side_effect=FinishedException)
        with patch.object(
            assistant,
            "get_display_title",
            return_value={"title": "诗客"},
        ):
            with self.assertRaises(FinishedException):
                await assistant._authorize_and_apply(
                    matcher, bot, _event(), "【称号】昵称"
                )
        self.assertIsNone(gm.get_card_record("20001", "10001"))

    async def test_ordinary_member_can_create_and_management_boundary_remains(self):
        matcher_finish = AsyncMock(side_effect=FinishedException)
        with patch.object(assistant.activity, "finish", matcher_finish):
            with self.assertRaises(FinishedException):
                await assistant.handle_activity(_event(), Message("创建 诗会"))
        current = gm.get_activity("20001")
        self.assertEqual(current["creator_id"], "10001")
        self.assertTrue(assistant._can_manage_activity(_event(10001), current))
        self.assertFalse(assistant._can_manage_activity(_event(10002), current))
        with patch.object(assistant, "get_event_permission_level", return_value=3):
            self.assertTrue(assistant._can_manage_activity(_event(10003), current))

    async def test_ordinary_member_can_wake_a_mentioned_group_member(self):
        bot = AsyncMock()
        bot.self_id = 99999
        event = _event(
            message=Message(
                [MessageSegment.text("/唤醒 "), MessageSegment.at(10002)]
            )
        )
        finish = AsyncMock(side_effect=FinishedException)
        require_bot_manager = AsyncMock()
        get_member = AsyncMock(return_value={"role": "member"})
        group_poke = AsyncMock()
        with (
            patch.object(assistant.wake, "finish", finish),
            patch.object(
                assistant,
                "get_event_permission_level",
                side_effect=AssertionError("ordinary wake must not check bot permissions"),
            ),
            patch.object(assistant, "allow_poke", return_value=True),
            patch.object(assistant, "require_bot_manager", require_bot_manager),
            patch.object(assistant, "get_member", get_member),
            patch.object(assistant, "group_poke", group_poke),
        ):
            with self.assertRaises(FinishedException):
                await assistant.handle_wake(bot, event)

        require_bot_manager.assert_awaited_once_with(bot, "20001")
        get_member.assert_awaited_once_with(bot, "20001", "10002")
        group_poke.assert_awaited_once_with(bot, "20001", "10002")
        self.assertIn("醒醒，诗会尚未散席", finish.await_args.args[0])

    async def test_group_management_intro_marks_wake_as_public(self):
        finish = AsyncMock(side_effect=FinishedException)
        with patch.object(assistant.group_management_intro, "finish", finish):
            with self.assertRaises(FinishedException):
                await assistant.handle_group_management_intro()

        text = finish.await_args.args[0]
        self.assertIn("/唤醒 @某人 - 请本猫戳醒群友", text)
        self.assertNotIn("唤醒 @某人 - 请本猫戳醒群友（需群务掌柜权限）", text)

    async def test_disabled_group_skips_message_index_storage(self):
        with (
            patch.object(assistant, "is_feature_enabled", return_value=False),
            patch.object(assistant, "index_message") as index_message,
        ):
            await assistant.handle_message_index(_event())

        index_message.assert_not_called()

    async def test_disabled_group_skips_notice_storage(self):
        for notice_type in ("essence", "group_msg_emoji_like"):
            event = SimpleNamespace(
                model_dump=lambda notice_type=notice_type: {
                    "notice_type": notice_type,
                    "group_id": 20001,
                    "message_id": 1,
                    "likes": [{"count": 3}],
                }
            )
            with (
                patch.object(assistant, "is_feature_enabled", return_value=False),
                patch.object(assistant, "sync_essence_event") as sync_essence_event,
                patch.object(assistant, "record_emoji_likes") as record_emoji_likes,
            ):
                await assistant.handle_group_notice(event)

            sync_essence_event.assert_not_called()
            record_emoji_likes.assert_not_called()

    async def test_disabled_group_preserves_due_card_job_without_platform_call(self):
        job = {"group_id": "20001", "user_id": "10001"}
        with (
            patch.object(assistant, "due_card_jobs", return_value=[job]),
            patch.object(assistant, "is_feature_enabled", return_value=False),
            patch.object(assistant, "get_card_record") as get_card_record,
            patch.object(assistant, "remove_card_job") as remove_card_job,
            patch.object(assistant, "retry_card_job") as retry_card_job,
            patch.object(assistant, "get_bot") as get_bot,
        ):
            await assistant.process_card_queue()

        get_card_record.assert_not_called()
        remove_card_job.assert_not_called()
        retry_card_job.assert_not_called()
        get_bot.assert_not_called()

    async def test_disabled_group_is_filtered_before_activity_expiry_or_api(self):
        def expire_due_activities(*, group_filter):
            self.assertFalse(group_filter("20001"))
            return []

        with (
            patch.object(assistant, "is_feature_enabled", return_value=False),
            patch.object(
                assistant,
                "expire_due_activities",
                side_effect=expire_due_activities,
            ) as expire,
            patch.object(assistant, "get_bot") as get_bot,
        ):
            await assistant.process_activity_deadlines()

        expire.assert_called_once()
        get_bot.assert_not_called()
