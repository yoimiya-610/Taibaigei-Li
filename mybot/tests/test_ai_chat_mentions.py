import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11.bot import _check_at_me, _check_nickname

from mybot.common.message_utils import get_chat_text, is_chat_addressed
from mybot.plugins import ai_chat


def group_event(message: Message | str, *, to_me: bool = False) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 1,
            "user_id": 10001,
            "group_id": 20001,
            "message": Message(message),
            "original_message": Message(message),
            "raw_message": str(message),
            "font": 0,
            "sender": {"user_id": 10001, "nickname": "群友", "role": "member"},
            "to_me": to_me,
        }
    )


class ChatMentionTest(unittest.TestCase):
    def test_real_mention_anywhere_after_adapter_processing(self):
        at = MessageSegment.at(99999)
        for message in (
            Message(at) + " 你好",
            Message("你好 ") + at + " 聊聊吧",
            Message("你好 ") + at,
            MessageSegment.at(10002) + " 也来听听 " + at + " 聊聊吧",
        ):
            with self.subTest(message=str(message)):
                event = group_event(message)
                _check_at_me(None, event)
                self.assertTrue(is_chat_addressed(event))
                self.assertNotIn("[CQ:at", get_chat_text(event))

    def test_copied_mention_anywhere_and_qq_spacing(self):
        for text, expected in (
            ("@李太白给 你好", "你好"),
            ("你好 @李太白给 聊聊吧", "你好  聊聊吧"),
            ("你好@李太白给", "你好"),
            ("@李太白给\u2005你好", "你好"),
            ("＠李太白给\u00a0你好", "你好"),
            ("@李太白给，聊聊吧", "，聊聊吧"),
            ("@李太白给\n清除记忆", "清除记忆"),
            ("@李太白给 @李太白给", ""),
        ):
            with self.subTest(text=text):
                event = group_event(text)
                self.assertTrue(is_chat_addressed(event))
                self.assertEqual(get_chat_text(event), expected)
                self.assertEqual(event.get_plaintext(), text)
                self.assertFalse(event.is_tome())

    def test_member_ids_and_other_text_do_not_address_bot(self):
        for message in (
            MessageSegment.at(10002) + " 你好",
            MessageSegment.at("all") + " 你好",
            "@群友 你好",
            "李太白给在吗",
            "@李太白给的小号 你好",
            "@李太白给bot 你好",
            MessageSegment.image("https://example.com/@李太白给"),
        ):
            with self.subTest(message=str(message)):
                self.assertFalse(is_chat_addressed(group_event(Message(message))))

    def test_existing_reply_private_and_nickname_addressing_is_preserved(self):
        reply_event = group_event("旧式回复", to_me=True)
        self.assertTrue(is_chat_addressed(reply_event))
        self.assertEqual(get_chat_text(reply_event), "旧式回复")

        nickname_event = group_event("太白 你好")
        bot = SimpleNamespace(config=SimpleNamespace(nickname={"太白"}))
        _check_nickname(bot, nickname_event)
        self.assertTrue(is_chat_addressed(nickname_event))
        self.assertEqual(get_chat_text(nickname_event), "你好")

        private_data = group_event("私聊你好").model_dump()
        private_data.update(message_type="private", sub_type="friend")
        private_data.pop("group_id")
        private_event = PrivateMessageEvent.model_validate(private_data)
        _check_at_me(None, private_event)
        self.assertTrue(is_chat_addressed(private_event))
        self.assertEqual(get_chat_text(private_event), "私聊你好")


class ChatMentionHandlerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ai_chat.chat_history.clear()
        self.addCleanup(ai_chat.chat_history.clear)
        for name, value in (
            ("is_feature_enabled", True),
            ("is_configured", True),
            ("consume_quota", SimpleNamespace(allowed=True)),
            ("build_system_prompt", "测试角色提示"),
        ):
            patcher = patch.object(ai_chat, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_matcher_rule_accepts_middle_and_copied_mentions(self):
        for message in (
            Message("你好 ") + MessageSegment.at(99999) + " 聊聊吧",
            Message("你好 @李太白给 聊聊吧"),
        ):
            with self.subTest(message=str(message)):
                self.assertTrue(await ai_chat.ai_chat.rule(None, group_event(message), {}))
        self.assertFalse(await ai_chat.ai_chat.rule(None, group_event("@群友 你好"), {}))

    async def test_copied_mention_is_removed_from_history_and_ai_request(self):
        event = group_event("@李太白给\u2005你好")
        completion = AsyncMock(return_value="（提壶）你好，小友。")
        with (
            patch.object(ai_chat, "run_readonly_tool_conversation", completion),
            patch.object(ai_chat.ai_chat, "send", new_callable=AsyncMock) as send,
        ):
            await ai_chat.handle_ai_chat(event)
        self.assertEqual(completion.await_args.args[0][-1]["content"], "你好")
        self.assertEqual(ai_chat.chat_history[ai_chat.get_chat_history_key(event)][0]["content"], "你好")
        send.assert_awaited_once()
        self.assertTrue(ai_chat.has_ending_poem(send.await_args.args[0]))

    async def test_copied_mention_can_clear_memory(self):
        event = group_event("@李太白给 清除记忆")
        key = ai_chat.get_chat_history_key(event)
        ai_chat.chat_history[key].append({"role": "user", "content": "旧对话"})
        with (
            patch.object(ai_chat, "run_readonly_tool_conversation", new_callable=AsyncMock) as completion,
            patch.object(ai_chat.ai_chat, "send", new_callable=AsyncMock) as send,
        ):
            await ai_chat.handle_ai_chat(event)
        self.assertEqual(ai_chat.chat_history[key], [])
        completion.assert_not_awaited()
        send.assert_awaited_once()

    async def test_empty_mention_and_known_commands_do_not_call_ai(self):
        with (
            patch.object(ai_chat, "run_readonly_tool_conversation", new_callable=AsyncMock) as completion,
            patch.object(ai_chat.ai_chat, "send", new_callable=AsyncMock) as send,
        ):
            await ai_chat.handle_ai_chat(group_event("@李太白给\u2005"))
            send.assert_awaited_once()
            self.assertIn("什么都没说", send.await_args.args[0])
            await ai_chat.handle_ai_chat(group_event("@李太白给 /帮助"))
            completion.assert_not_awaited()
            send.assert_awaited_once()

    async def test_direct_mentions_do_not_also_trigger_random_reply(self):
        for message in (
            Message("你好 ") + MessageSegment.at(99999) + " 聊聊吧",
            Message("你好 @李太白给 聊聊吧"),
        ):
            with (
                self.subTest(message=str(message)),
                patch.object(ai_chat.random, "random", return_value=0) as random_roll,
                patch.object(ai_chat.ai_random, "send", new_callable=AsyncMock) as send,
            ):
                await ai_chat.handle_random(group_event(message))
                random_roll.assert_not_called()
                send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
