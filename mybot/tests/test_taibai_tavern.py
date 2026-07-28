from pathlib import Path
from tempfile import TemporaryDirectory
from itertools import combinations
import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from mybot.common.help_registry import CATEGORY_META
from mybot.plugins import points
from mybot.plugins import taibai_tavern


class TaibaiTavernTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.old_points_file = points.POINTS_FILE
        self.old_tavern_file = taibai_tavern.DATA_FILE
        base = Path(self.tmp_dir.name)
        points.POINTS_FILE = base / "points.json"
        taibai_tavern.DATA_FILE = base / "taibai_tavern.json"

    def tearDown(self):
        points.POINTS_FILE = self.old_points_file
        taibai_tavern.DATA_FILE = self.old_tavern_file
        self.tmp_dir.cleanup()

    def test_parse_wine_money_accepts_positive_integer_aliases(self):
        self.assertEqual(taibai_tavern.parse_wine_money("10"), 10)
        self.assertEqual(taibai_tavern.parse_wine_money("10酒钱"), 10)
        self.assertEqual(taibai_tavern.parse_wine_money("8 枚"), 8)
        self.assertIsNone(taibai_tavern.parse_wine_money("0"))
        self.assertIsNone(taibai_tavern.parse_wine_money("-1"))
        self.assertIsNone(taibai_tavern.parse_wine_money("一百"))

    def test_parse_start_args_accepts_random_or_fixed_bad_sign_count(self):
        self.assertEqual(
            taibai_tavern.parse_start_args("10"),
            {"wine_money": 10, "mode": taibai_tavern.RANDOM_MODE},
        )
        self.assertEqual(taibai_tavern.parse_start_args("10 3"), {"wine_money": 10, "mode": 3})
        self.assertEqual(taibai_tavern.parse_start_args("10 四凶"), {"wine_money": 10, "mode": 4})
        self.assertEqual(
            taibai_tavern.parse_start_args("10 随机"),
            {"wine_money": 10, "mode": taibai_tavern.RANDOM_MODE},
        )
        self.assertIsNone(taibai_tavern.parse_start_args("10 5"))
        self.assertIsNone(taibai_tavern.parse_start_args("10 3 多余"))

    def test_parse_sign_position_accepts_one_to_five(self):
        self.assertEqual(taibai_tavern.parse_sign_position("1"), 1)
        self.assertEqual(taibai_tavern.parse_sign_position("三号签"), 3)
        self.assertEqual(taibai_tavern.parse_sign_position("5"), 5)
        self.assertIsNone(taibai_tavern.parse_sign_position("0"))
        self.assertIsNone(taibai_tavern.parse_sign_position("6"))
        self.assertIsNone(taibai_tavern.parse_sign_position("随便"))

    def test_parse_ink_trace_guess_accepts_known_images(self):
        self.assertEqual(taibai_tavern.parse_ink_trace_guess("月"), "月")
        self.assertEqual(taibai_tavern.parse_ink_trace_guess("墨宝 剑"), "剑")
        self.assertIsNone(taibai_tavern.parse_ink_trace_guess("山"))

    def test_tavern_has_separate_help_category(self):
        self.assertIn("太白酒馆", CATEGORY_META)
        self.assertEqual(taibai_tavern.HELP_ITEMS[0].category, "太白酒馆")
        self.assertIn("墨宝寻踪", taibai_tavern.COMMAND_ALIASES)

    def test_tavern_help_owns_wine_exchange_copy(self):
        tavern_help = taibai_tavern._render_tavern_help()

        self.assertIn("1 积分，换 10 酒钱", tavern_help)
        self.assertIn("今日翻签，来日添新局", tavern_help)
        self.assertIn("/墨宝寻踪 酒钱数", tavern_help)

    def test_points_exchange_to_wine_at_one_to_ten(self):
        self.assertEqual(taibai_tavern.points_to_wine(1), 10)
        self.assertEqual(taibai_tavern.points_to_wine(12), 120)
        self.assertEqual(taibai_tavern.points_needed_for_wine(1), 1)
        self.assertEqual(taibai_tavern.points_needed_for_wine(10), 1)
        self.assertEqual(taibai_tavern.points_needed_for_wine(11), 2)
        self.assertEqual(taibai_tavern.parse_exchange_points("5积分"), 5)
        self.assertIsNone(taibai_tavern.parse_exchange_points("0"))

    def test_reward_uses_fixed_multiplier_steps(self):
        stake = 100
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 0), 0)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 1), 110)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 2), 150)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 3), 230)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 4), 380)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 5), 750)

    def test_fixed_bad_count_modes_use_higher_risk_multipliers(self):
        stake = 100
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 1, 1), 100)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 4, 1), 250)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 1, 2), 130)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 3, 2), 600)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 1, 3), 200)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 2, 3), 800)
        self.assertEqual(taibai_tavern.calculate_reward_wine(stake, 1, 4), 400)
        self.assertEqual(taibai_tavern.current_multiplier_text(2, 1), "1.25x")

    def test_give_up_refunds_twenty_percent(self):
        self.assertEqual(taibai_tavern.calculate_refund_wine(100), 20)
        self.assertEqual(taibai_tavern.calculate_refund_wine(50), 10)

    def test_ink_trace_reward_and_stargaze_cost(self):
        self.assertEqual(taibai_tavern.calculate_ink_trace_reward_wine(100, "云"), 260)
        self.assertEqual(taibai_tavern.calculate_ink_trace_reward_wine(100, "花"), 300)
        self.assertLess(
            taibai_tavern.INK_TRACE_TREASURE_WEIGHTS["花"],
            taibai_tavern.INK_TRACE_TREASURE_WEIGHTS["云"],
        )
        self.assertEqual(taibai_tavern.calculate_ink_trace_reward_wine(15, "月"), 30)
        self.assertEqual(taibai_tavern.calculate_ink_trace_stargaze_cost(100), 60)
        self.assertEqual(taibai_tavern.calculate_ink_trace_stargaze_cost(5), 3)

    def test_ink_trace_stargaze_keeps_optimal_return_below_cost(self):
        cost_ratio = taibai_tavern.calculate_ink_trace_stargaze_cost(100) / 100
        for option_count in taibai_tavern.INK_TRACE_OPTION_COUNTS:
            for options in combinations(taibai_tavern.INK_TRACE_IMAGES, option_count):
                for excluded in options:
                    remaining = [option for option in options if option != excluded]
                    total_weight = sum(taibai_tavern.INK_TRACE_TREASURE_WEIGHTS[option] for option in remaining)
                    best_return_ratio = max(
                        taibai_tavern.INK_TRACE_TREASURE_WEIGHTS[option]
                        / total_weight
                        * (taibai_tavern.get_ink_trace_reward_tenths(option) / 10)
                        for option in remaining
                    )
                    with self.subTest(options=options, excluded=excluded):
                        self.assertLess(best_return_ratio - cost_ratio, 1)
                        self.assertLess(best_return_ratio / (1 + cost_ratio), 1)

    def test_new_ink_trace_game_uses_three_or_four_options(self):
        with patch("mybot.plugins.taibai_tavern.random.choice", return_value=3):
            with patch("mybot.plugins.taibai_tavern.random.sample", return_value=["酒", "月", "剑"]):
                with patch("mybot.plugins.taibai_tavern.random.choices", return_value=["月"]) as choices:
                    game = taibai_tavern.new_ink_trace_game(20, "u1", "g1", "太白")

        self.assertEqual(game["options"], ["酒", "月", "剑"])
        self.assertEqual(game["treasure"], "月")
        self.assertEqual(game["stake_wine"], 20)
        self.assertFalse(game["stargazed"])
        self.assertEqual(choices.call_args.kwargs["weights"], [18, 16, 14])

    def test_reveal_wrong_ink_trace_option_excludes_only_wrong_image(self):
        game = {
            "options": ["酒", "月", "剑"],
            "treasure": "月",
            "excluded": [],
            "stargazed": False,
        }
        with patch("mybot.plugins.taibai_tavern.random.choice", return_value="剑"):
            revealed = taibai_tavern.reveal_wrong_ink_trace_option(game)

        self.assertEqual(revealed, "剑")
        self.assertEqual(game["excluded"], ["剑"])
        self.assertTrue(game["stargazed"])

    def test_new_sign_deck_supports_zero_to_four_bad_signs(self):
        for bad_count in (0, 1, 2, 3, 4):
            with self.subTest(bad_count=bad_count):
                deck = taibai_tavern.new_sign_deck(bad_count)
                self.assertEqual(len(deck), taibai_tavern.SIGN_COUNT)
                self.assertEqual(deck.count("凶"), bad_count)
                self.assertEqual(deck.count("吉"), taibai_tavern.SIGN_COUNT - bad_count)

    def test_choose_bad_sign_count_is_weighted_between_zero_and_two(self):
        with patch("mybot.plugins.taibai_tavern.random.choices", return_value=[2]) as choices:
            self.assertEqual(taibai_tavern.choose_bad_sign_count(), 2)
        args, kwargs = choices.call_args
        self.assertEqual(args[0], (0, 1, 2))
        self.assertEqual(kwargs["weights"], (10, 35, 55))

    def test_continue_expectation_uses_public_prior_not_hidden_deck(self):
        self.assertAlmostEqual(taibai_tavern.calculate_continue_expectation_wine(100, 0), 78.1)
        self.assertAlmostEqual(taibai_tavern.calculate_continue_expectation_wine(100, 1), 100.35211267605634)
        self.assertAlmostEqual(taibai_tavern.calculate_continue_expectation_wine(100, 4), 441.1764705882353)

    def test_multiplier_plan_keeps_optimal_return_under_entry_cost(self):
        self.assertAlmostEqual(taibai_tavern.calculate_optimal_return_ratio(), 0.7810000000000001)
        self.assertLess(taibai_tavern.calculate_optimal_return_ratio(), 0.8)
        self.assertAlmostEqual(taibai_tavern.calculate_optimal_return_ratio(1), 0.8)
        self.assertAlmostEqual(taibai_tavern.calculate_optimal_return_ratio(2), 0.78)
        self.assertAlmostEqual(taibai_tavern.calculate_optimal_return_ratio(3), 0.8)
        self.assertAlmostEqual(taibai_tavern.calculate_optimal_return_ratio(4), 0.8)

    def test_wine_store_adds_and_spends_without_points_cashback(self):
        with self.subTest("add and spend"):
            taibai_tavern.add_wine_money("u1", "g1", 30)
            result = taibai_tavern.spend_wine_money("u1", "g1", 12)

            self.assertTrue(result["ok"])
            self.assertEqual(result["balance"], 18)
            self.assertEqual(taibai_tavern.get_wine_money("u1", "g1"), 18)

        with self.subTest("cannot overspend"):
            result = taibai_tavern.spend_wine_money("u1", "g1", 20)

            self.assertFalse(result["ok"])
            self.assertEqual(result["balance"], 18)

    def test_exchange_points_to_wine_requires_explicit_command(self):
        points.add_points("u2", "g1", 100)

        result = taibai_tavern.exchange_points_to_wine("u2", "g1", 3)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["exchanged_wine"], 30)
        self.assertEqual(result["wine_balance"], 30)
        self.assertEqual(points.get_points("u2", "g1")["current"], 97)

    def test_exchange_points_to_wine_rejects_insufficient_points(self):
        points.add_points("u3", "g1", 2)

        result = taibai_tavern.exchange_points_to_wine("u3", "g1", 5)

        self.assertEqual(result["status"], "insufficient_points")
        self.assertEqual(result["point_cost"], 5)
        self.assertEqual(points.get_points("u3", "g1")["current"], 2)

    def test_prepare_wine_stake_only_spends_existing_wine(self):
        points.add_points("u4", "g1", 100)
        taibai_tavern.add_wine_money("u4", "g1", 3)

        result = taibai_tavern.prepare_wine_stake("u4", "g1", 8)

        self.assertEqual(result["status"], "insufficient_wine")
        self.assertEqual(result["shortfall"], 5)
        self.assertEqual(result["point_cost"], 1)
        self.assertEqual(taibai_tavern.get_wine_money("u4", "g1"), 3)
        self.assertEqual(points.get_points("u4", "g1")["current"], 100)

        taibai_tavern.add_wine_money("u4", "g1", 10)
        ok_result = taibai_tavern.prepare_wine_stake("u4", "g1", 8)
        self.assertEqual(ok_result["status"], "ok")
        self.assertEqual(ok_result["wine_balance"], 5)


if __name__ == "__main__":
    unittest.main()
