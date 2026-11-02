import unittest
from unittest.mock import AsyncMock

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common import group_platform
from mybot.common.onebot_capabilities import (
    ImplementationFamily,
    ImplementationInfo,
    onebot_capability_registry,
)
from mybot.plugins import profile_like


class ProfileLikeTest(unittest.TestCase):
    def test_target_is_read_from_onebot_at_segment(self):
        message = Message(
            [
                MessageSegment.text("同名群友 123456 "),
                MessageSegment.at("all"),
                MessageSegment.at(123456),
            ]
        )

        self.assertEqual(profile_like.extract_profile_like_target(message), "123456")

    def test_plain_text_never_becomes_a_target(self):
        message = Message(MessageSegment.text("同名群友 123456"))

        self.assertIsNone(profile_like.extract_profile_like_target(message))

    def test_help_and_aliases_expose_the_ink_like_command(self):
        self.assertEqual(
            profile_like.HELP_ITEMS[0].text,
            "/墨赞 - 给群友资料卡落十枚墨赞",
        )
        self.assertEqual(
            set(profile_like.COMMAND_ALIASES),
            {"墨赞", "点赞", "赞名片", "资料卡点赞"},
        )

    def test_success_mentions_the_target_and_keeps_four_line_poem(self):
        message = profile_like.build_profile_like_success("123456")

        self.assertEqual(message[1].type, "at")
        self.assertEqual(str(message[1].data["qq"]), "123456")
        plain_text = message.extract_plain_text()
        self.assertIn("墨赞已成：10 次", plain_text)
        poem = plain_text.split("『", 1)[1].rsplit("』", 1)[0]
        self.assertEqual(len(poem.splitlines()), 4)

    def test_failure_copy_is_role_safe(self):
        self.assertIn("本猫", profile_like.FAILED_MESSAGE)
        self.assertNotIn("API", profile_like.FAILED_MESSAGE)
        self.assertNotIn("模型", profile_like.FAILED_MESSAGE)
        poem = profile_like.FAILED_MESSAGE.split("『", 1)[1].rsplit("』", 1)[0]
        self.assertEqual(len(poem.splitlines()), 4)


class ProfileLikePlatformTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        generation = onebot_capability_registry.begin_connection()
        onebot_capability_registry.apply_probe(
            generation,
            ImplementationInfo("OneBot", "1.0.0", "v11", ImplementationFamily.ONEBOT),
            healthy=True,
            issue=None,
        )

    async def asyncTearDown(self):
        onebot_capability_registry.mark_disconnected()

    async def test_send_user_like_uses_onebot_action_and_numeric_parameters(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(return_value=None)

        await group_platform.send_user_like(bot, "123456", times=10)

        bot.call_api.assert_awaited_once_with(
            "send_like",
            user_id=123456,
            times=10,
        )

    async def test_send_user_like_rejects_out_of_range_times(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(return_value=None)

        with self.assertRaisesRegex(
            group_platform.PlatformOperationError,
            "invalid_request",
        ):
            await group_platform.send_user_like(bot, "123456", times=11)

        bot.call_api.assert_not_awaited()

    async def test_platform_failure_keeps_private_detail_wrapped(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(side_effect=RuntimeError("private detail"))

        with self.assertRaisesRegex(
            group_platform.PlatformOperationError,
            "unavailable",
        ):
            await group_platform.send_user_like(bot, "123456", times=10)


if __name__ == "__main__":
    unittest.main()
