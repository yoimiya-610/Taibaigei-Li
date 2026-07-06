import unittest

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common.message_utils import get_first_at_user_id
from mybot.plugins import love


class _FirstChoice:
    @staticmethod
    def choice(items):
        return items[0]


class LoveInteractionsTest(unittest.TestCase):
    def test_get_first_at_user_id_reads_onebot_segments(self):
        message = Message(
            [
                MessageSegment.text("/缘分签 "),
                MessageSegment.at("all"),
                MessageSegment.text(" "),
                MessageSegment.at(123456),
            ]
        )

        self.assertEqual(get_first_at_user_id(message), "123456")

    def test_love_help_registers_new_interactions(self):
        help_texts = {item.text for item in love.HELP_ITEMS if item.category == "情感互动"}

        self.assertIn("/缘分签 @某人 - 抽今日缘分", help_texts)
        self.assertIn("/夸夸 @某人 - 夸赞群友", help_texts)
        self.assertIn("/借酒说话 内容 - 把话说软", help_texts)
        self.assertIn("/今日心动 - 抽今日心动小事", help_texts)
        self.assertIn("缘分签", love.COMMAND_ALIASES)
        self.assertIn("借酒说话", love.COMMAND_ALIASES)

    def test_fate_pick_is_stable_for_pair(self):
        first = love._pick_fate("2026-07-03", "9988", "10001", "10002")
        second = love._pick_fate("2026-07-03", "9988", "10002", "10001")

        self.assertEqual(first, second)

    def test_render_praise_message_uses_sender_and_target(self):
        text = love._render_praise_message("阿甲", "阿乙", rng=_FirstChoice)

        self.assertIn("阿甲", text)
        self.assertIn("阿乙", text)
        self.assertIn("李太白给·夸夸笺", text)

    def test_today_heartbeat_is_stable_for_user_and_date(self):
        first = love._render_today_heartbeat("阿甲", "2026-07-03", "10001")
        second = love._render_today_heartbeat("阿甲", "2026-07-03", "10001")

        self.assertEqual(first, second)
        self.assertIn("阿甲", first)
        self.assertIn("今日心动", first)

    def test_tipsy_prompt_keeps_original_text(self):
        prompt = love._build_tipsy_prompt("阿甲", "最近辛苦了，想请你喝杯奶茶")

        self.assertIn("阿甲", prompt)
        self.assertIn("最近辛苦了，想请你喝杯奶茶", prompt)
        self.assertIn("不改变原意", prompt)


if __name__ == "__main__":
    unittest.main()
