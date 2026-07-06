import random
import unittest

import mybot.bot  # noqa: F401
from mybot.plugins import fun


class SequenceRng:
    def __init__(self, values):
        self.values = list(values)

    def choice(self, _items):
        if not self.values:
            raise AssertionError("sequence rng exhausted")
        return self.values.pop(0)


class FunPaidInteractionsTest(unittest.TestCase):
    def test_fun_help_registers_paid_commands(self):
        help_texts = {item.text for item in fun.HELP_ITEMS if item.category == "趣味功能"}

        self.assertIn("/发疯文学 主题 - 20积分", help_texts)
        self.assertIn("/废话文学 内容 - 20积分", help_texts)
        self.assertIn("/赛博算卦 问题 - 普通20/高级100积分", help_texts)
        self.assertIn("发疯文学", fun.COMMAND_ALIASES)
        self.assertIn("赛博算卦", fun.COMMAND_ALIASES)

    def test_divination_tier_parser(self):
        self.assertEqual(
            fun.parse_divination_request("要不要出门"),
            ("normal", "要不要出门", fun.DIVINATION_NORMAL_COST),
        )
        self.assertEqual(
            fun.parse_divination_request("高级 要不要出门"),
            ("advanced", "要不要出门", fun.DIVINATION_ADVANCED_COST),
        )
        self.assertEqual(
            fun.parse_divination_request("普通 要不要出门"),
            ("normal", "要不要出门", fun.DIVINATION_NORMAL_COST),
        )

    def test_draw_hexagram_uses_three_coin_lines(self):
        rng = SequenceRng(["背"] * 18)
        cast = fun.draw_hexagram(rng)

        self.assertEqual(cast["hexagram"], {"number": 1, "name": "乾为天"})
        self.assertEqual(cast["changed_hexagram"], {"number": 2, "name": "坤为地"})
        self.assertEqual(cast["changing_lines"], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(line["value"] == 9 for line in cast["lines"]))

    def test_advanced_divination_renders_process(self):
        rng = SequenceRng(["背"] * 18)
        text = fun.render_advanced_divination("此事可行否", "阿甲", rng)

        self.assertIn("周易赛博算卦", text)
        self.assertIn("起卦法：三枚铜钱起六爻", text)
        self.assertIn("初爻：背背背=9", text)
        self.assertIn("本卦：第1卦 乾为天", text)
        self.assertIn("变卦：第2卦 坤为地", text)
        self.assertIn("模糊回答：", text)
        self.assertIn("消耗 100 积分", text)

    def test_normal_divination_renders_compact_result(self):
        text = fun.render_normal_divination("今天适合摸鱼吗", "阿甲", random.Random(1))

        self.assertIn("赛博算卦", text)
        self.assertIn("档位：随便算算", text)
        self.assertIn("消耗 20 积分", text)
        self.assertIn("卦象：第", text)
        self.assertIn("模糊回答：若问偷闲摸鱼", text)

    def test_paid_ai_prompts_keep_user_content(self):
        mad_prompt = fun._build_mad_prompt("阿甲", "上班")
        nonsense_prompt = fun._build_nonsense_prompt("阿乙", "我想睡觉")

        self.assertIn("上班", mad_prompt)
        self.assertIn("发疯文学", mad_prompt)
        self.assertIn("我想睡觉", nonsense_prompt)
        self.assertIn("废话文学", nonsense_prompt)


if __name__ == "__main__":
    unittest.main()
