import unittest

import mybot.bot  # noqa: F401
from mybot.common.ai_context_registry import build_relevant_ai_context
from mybot.common.ai_public_play_guides import (
    build_public_play_guide_context,
    select_public_play_guides,
    should_reference_public_play_guides,
)
from mybot.plugins import ai_chat


class PublicPlayGuideTest(unittest.TestCase):
    def test_first_batch_entries_match_clear_rule_questions(self):
        cases = {
            "每日签到积分怎么算": "fortune_signin",
            "补签多少钱": "fortune_makeup",
            "积分怎么查看": "points_account",
            "低保怎么领": "low_income",
            "称号怎么查看": "titles",
            "酒馆怎么玩": "taibai_tavern",
        }

        for message, key in cases.items():
            with self.subTest(message=message):
                keys = {entry.key for entry in select_public_play_guides(message)}
                self.assertIn(key, keys)

    def test_first_batch_entries_match_definition_questions(self):
        cases = {
            "签到是啥": "fortune_signin",
            "什么是补签": "fortune_makeup",
            "积分是干嘛的": "points_account",
            "低保有什么用": "low_income",
            "称号啥意思": "titles",
            "太白酒馆是什么": "taibai_tavern",
        }

        for message, key in cases.items():
            with self.subTest(message=message):
                keys = {entry.key for entry in select_public_play_guides(message)}
                self.assertIn(key, keys)

    def test_trigger_is_strict_for_unrelated_requests(self):
        self.assertFalse(should_reference_public_play_guides("今天陪本猫闲聊两句"))
        self.assertFalse(should_reference_public_play_guides("帮我写一首签到主题的诗"))
        self.assertFalse(should_reference_public_play_guides("积分像月亮一样圆，续写这句话"))
        self.assertFalse(should_reference_public_play_guides("这句诗是啥意思，昨日忘了签到"))

    def test_only_relevant_entries_are_rendered(self):
        context = build_public_play_guide_context("补签多少钱")

        self.assertIn("[fortune_makeup]", context)
        self.assertNotIn("[fortune_signin]", context)
        self.assertNotIn("[low_income]", context)
        self.assertNotIn("[taibai_tavern]", context)

    def test_realtime_status_queries_explain_readonly_ai_boundary(self):
        context = build_public_play_guide_context("我有多少积分")

        self.assertIn("[personal_realtime_status]", context)
        self.assertIn("只读卷册据实回答", context)
        self.assertIn("不能查询他人或其他群", context)
        self.assertIn("/我的卷册", context)
        self.assertNotIn("[points_account]", context)

    def test_sensitive_or_hidden_details_do_not_enter_context(self):
        context = build_public_play_guide_context("每日签到积分怎么算")

        self.assertIn("[fortune_signin]", context)
        self.assertNotIn("万分之一", context)
        self.assertNotIn("气运之神", context)
        self.assertNotIn("？？？", context)
        self.assertNotIn("UNKNOWN_FORTUNE", context)
        self.assertNotIn("secret_", context)

    def test_multi_database_context_can_attach_capabilities_and_guides(self):
        context = build_relevant_ai_context("你有什么功能，低保怎么领")

        self.assertIn("《李太白给公开本事簿》", context)
        self.assertIn("《李太白给公开玩法详解》", context)
        self.assertIn("[low_income]", context)

    def test_ai_chat_attaches_public_play_guides_only_when_relevant(self):
        guide_prompt = ai_chat.build_system_prompt("酒馆怎么玩")
        definition_prompt = ai_chat.build_system_prompt("签到是啥")
        normal_prompt = ai_chat.build_system_prompt("帮我生成一首诗歌")

        self.assertIn("《李太白给公开玩法详解》", guide_prompt)
        self.assertIn("《李太白给公开玩法详解》", definition_prompt)
        self.assertNotIn("《李太白给公开玩法详解》", normal_prompt)


if __name__ == "__main__":
    unittest.main()
