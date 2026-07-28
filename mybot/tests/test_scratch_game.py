import unittest

import mybot.bot  # noqa: F401
from mybot.plugins_disabled import scratch


def card(name: str) -> dict[str, str]:
    return {"name": name, "display": name}


class ScratchGameTest(unittest.TestCase):
    def test_parse_level_accepts_three_fixed_levels(self):
        self.assertEqual(scratch._parse_level("1"), 1)
        self.assertEqual(scratch._parse_level("2级"), 2)
        self.assertEqual(scratch._parse_level("三档"), 3)
        self.assertIsNone(scratch._parse_level("4"))
        self.assertIsNone(scratch._parse_level("50"))

    def test_parse_positions_requires_three_unique_cards(self):
        self.assertEqual(scratch._parse_positions("1 5 9"), [1, 5, 9])
        self.assertEqual(scratch._parse_positions("1，5，9"), [1, 5, 9])
        self.assertIsNone(scratch._parse_positions("1 1 2"))
        self.assertIsNone(scratch._parse_positions("1 2 10"))
        self.assertIsNone(scratch._parse_positions("1 2"))

    def test_calculate_reward_adds_selected_symbol_scores(self):
        reward, reason = scratch.calculate_reward([card("玉佩"), card("月魄"), card("空牌")], 2)

        self.assertEqual(reward, 190)
        self.assertIn("玉佩+50", reason)
        self.assertIn("月魄+140", reason)
        self.assertIn("空牌+0", reason)

    def test_expected_reward_stays_close_to_but_below_entry_cost(self):
        for level, config in scratch.LEVEL_CONFIGS.items():
            with self.subTest(level=level):
                self.assertLess(scratch.expected_reward(level), config["cost"])
                self.assertGreaterEqual(scratch.expected_reward(level) / config["cost"], 0.95)


if __name__ == "__main__":
    unittest.main()
