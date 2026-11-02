import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from mybot.common import ai_client
from mybot.common.ai_capability_prompt import (
    build_capability_prompt,
    should_reference_capability_prompt,
)
from mybot.plugins import ai_chat


FOUR_VERSE_POEM = (
    "『小友推窗邀月饮，\n"
    "人间灯火已阑珊。\n"
    "醉笔乱题三两字，\n"
    "天公笑我太清闲。』"
)


class AIChatHistoryTest(unittest.TestCase):
    def setUp(self):
        ai_chat.chat_history.clear()

    def tearDown(self):
        ai_chat.chat_history.clear()

    def test_rollback_removes_only_failed_request_entries(self):
        key = ("group", "20001", "10001")
        earlier = {"role": "assistant", "content": "旧回复"}
        failed_user = {"role": "user", "content": "失败请求"}
        concurrent = {"role": "user", "content": "并发请求"}
        failed_assistant = {"role": "assistant", "content": "未送达回复"}
        ai_chat.chat_history[key].extend(
            [earlier, failed_user, concurrent, failed_assistant]
        )

        ai_chat.rollback_history_entries(key, [failed_user, failed_assistant])

        self.assertEqual(ai_chat.chat_history[key], [earlier, concurrent])

    def test_capability_prompt_trigger_is_strict(self):
        self.assertTrue(should_reference_capability_prompt("你会干啥"))
        self.assertTrue(should_reference_capability_prompt("本猫能算卦吗"))
        self.assertTrue(should_reference_capability_prompt("这些功能怎么用"))
        self.assertFalse(should_reference_capability_prompt("帮我生成一首诗歌"))
        self.assertFalse(should_reference_capability_prompt("翻译这段英文"))
        self.assertFalse(should_reference_capability_prompt("今天陪我聊聊天"))

    def test_capability_prompt_uses_public_help_only(self):
        prompt = build_capability_prompt()

        self.assertIn("/帮助 - 查看公开功能菜单", prompt)
        self.assertIn("/游戏 - 查看历史小游戏玩法与开关", prompt)
        self.assertEqual(prompt.count("/游戏 - 查看历史小游戏玩法与开关"), 1)
        self.assertIn("[趣味功能]", prompt)
        self.assertNotIn("[小游戏]", prompt)
        self.assertNotIn("/小游戏状态", prompt)
        self.assertIn("/签到 - 每日运势签到", prompt)
        self.assertIn("/太白酒馆 - 酒馆总览与酒钱规则", prompt)
        self.assertNotIn("/管理员 - 管理群聊权限", prompt)
        self.assertNotIn("/功能列表 - 查看有权管理的群功能", prompt)

    def test_ai_chat_only_attaches_relevant_context_for_capability_queries(self):
        capability_prompt = ai_chat.build_system_prompt("你会干啥")
        normal_prompt = ai_chat.build_system_prompt("帮我生成一首诗歌")

        self.assertIn("《李太白给公开本事簿》", capability_prompt)
        self.assertIn("系统依据本轮问题选取的受控参考资料", capability_prompt)
        self.assertNotIn("《李太白给公开本事簿》", normal_prompt)
        self.assertNotIn("系统依据本轮问题选取的受控参考资料", normal_prompt)

    def test_readonly_tool_prompt_is_only_attached_when_group_tools_are_available(self):
        group_prompt = ai_chat.build_system_prompt(
            "我今天签到了吗",
            group_id="20001",
            user_id="10001",
            readonly_tools_available=True,
        )
        private_prompt = ai_chat.build_system_prompt(
            "我今天签到了吗",
            user_id="10001",
            readonly_tools_available=False,
        )

        self.assertIn("受控只读工具", group_prompt)
        self.assertIn("不能查询被 @ 的其他人或其他群", group_prompt)
        self.assertNotIn("受控只读工具", private_prompt)
        self.assertNotIn("deepseek", group_prompt.lower())
        self.assertNotIn("存储", group_prompt)


class AIClientCompatibilityTest(unittest.TestCase):
    def test_structured_parser_preserves_tool_call_fields(self):
        message = ai_client._parse_chat_message(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "先查账",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_my_points",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )

        self.assertEqual(message.reasoning_content, "先查账")
        self.assertEqual(message.tool_calls[0].id, "call_1")
        self.assertEqual(message.tool_calls[0].arguments, "{}")
        self.assertEqual(message.to_api_dict()["tool_calls"][0]["function"]["name"], "get_my_points")

    def test_legacy_chat_completion_still_returns_a_string(self):
        structured = ai_client.AIChatMessage(content="旧接口回答")
        with patch.object(
            ai_client,
            "chat_completion_message",
            AsyncMock(return_value=structured),
        ):
            reply = asyncio.run(
                ai_client.chat_completion(
                    [{"role": "user", "content": "照旧回答"}],
                    usage_checked=True,
                )
            )

        self.assertEqual(reply, "旧接口回答")


class AIChatEndingPoemTest(unittest.TestCase):
    def test_ending_poem_requires_four_nonempty_verses_at_the_end(self):
        self.assertTrue(ai_chat.has_ending_poem(f"正文\n\n{FOUR_VERSE_POEM}"))
        self.assertTrue(
            ai_chat.has_ending_poem(
                "正文\n\n『小友推窗邀月饮，人间灯火已阑珊。\n"
                "醉笔乱题三两字，天公笑我太清闲。』"
            )
        )
        self.assertFalse(ai_chat.has_ending_poem("正文\n\n『』"))
        self.assertFalse(ai_chat.has_ending_poem("『只有一句。』"))
        self.assertFalse(ai_chat.has_ending_poem(f"{FOUR_VERSE_POEM}\n正文"))

    def test_empty_wrapper_recovers_the_preceding_four_verse_poem(self):
        malformed = (
            "（醉眼一瞄）友友来了？\n\n"
            "小友推窗邀月饮，人间灯火已阑珊。\n"
            "醉笔乱题三两字，天公笑我太清闲。\n\n『』"
        )

        repaired = ai_chat.ensure_ending_poem(malformed)

        self.assertEqual(
            repaired,
            "（醉眼一瞄）友友来了？\n\n"
            "『小友推窗邀月饮，人间灯火已阑珊。\n"
            "醉笔乱题三两字，天公笑我太清闲。』",
        )
        self.assertTrue(ai_chat.has_ending_poem(repaired))
        self.assertNotIn("『』", repaired)

    def test_invalid_poem_block_is_replaced_with_fallback(self):
        fallback = ai_chat.FALLBACK_POEMS[0]
        with patch.object(ai_chat.random, "choice", return_value=fallback):
            repaired = ai_chat.ensure_ending_poem("正文\n\n『只有一句。』")

        self.assertEqual(repaired, f"正文\n\n{fallback}")
        self.assertTrue(ai_chat.has_ending_poem(repaired))

    def test_charm_notice_is_inserted_before_recovered_poem(self):
        malformed = (
            "（醉眼一瞄）友友来了？\n\n"
            "小友推窗邀月饮，人间灯火已阑珊。\n"
            "醉笔乱题三两字，天公笑我太清闲。\n\n『』"
        )
        notice = "（墨镜一推）诗情画意，当浮一白！魅力值 +10"

        reply = ai_chat.insert_before_ending_poem(malformed, notice)

        self.assertEqual(
            reply,
            "（醉眼一瞄）友友来了？\n\n"
            f"{notice}\n\n"
            "『小友推窗邀月饮，人间灯火已阑珊。\n"
            "醉笔乱题三两字，天公笑我太清闲。』",
        )
        self.assertTrue(ai_chat.has_ending_poem(reply))
        self.assertNotIn("『』", reply)


if __name__ == "__main__":
    unittest.main()
