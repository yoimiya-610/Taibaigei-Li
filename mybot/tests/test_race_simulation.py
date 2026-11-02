from collections import Counter
import random
import unittest

import mybot.bot  # noqa: F401
from mybot.plugins_disabled import race


class RaceSimulationTest(unittest.TestCase):
    def test_text_board_uses_stable_two_line_lanes(self):
        visual = race._render_race_board(race.HORSES[:4], [1, 8, 13, 20])
        lines = visual.splitlines()

        self.assertEqual(len(lines), 8)
        self.assertIn("① 烈焰神驹 01/20", lines[0])
        self.assertIn("④ 闪电兔兔 20/20", lines[6])
        self.assertNotIn("|", visual)
        self.assertNotIn("=", visual)
        for bar_line in lines[1::2]:
            bar = bar_line.strip()
            self.assertEqual(len(bar), race.PROGRESS_CELLS)
            self.assertLessEqual(set(bar), {"■", "□"})

    def test_exact_crossing_time_beats_lane_order(self):
        results = race._rank_results(
            12345,
            positions=[20, 20, 18, 17],
            finish_times=[6.75, 6.25, None, None],
        )

        self.assertEqual(results[0][0], 1)
        self.assertEqual(results[1][0], 0)

    def test_seed_replays_complete_race_state(self):
        race_state = {"horses": race.HORSES[:4], "seed": 987654321}

        first = race._simulate_race(race_state)
        second = race._simulate_race(race_state)

        self.assertEqual(first, second)
        self.assertEqual(len(first["finish_times"]), 4)
        self.assertIsNotNone(first["finish_times"][first["winner_idx"]])

    def test_story_frames_keep_all_events_in_three_acts(self):
        frames = []
        for round_num in range(1, 8):
            positions = [round_num * 2, round_num * 2 + 1, round_num, round_num + 2]
            if round_num == 7:
                positions[3] = race.FINISH_LINE
            frames.append(
                {
                    "round": round_num,
                    "positions": positions,
                    "visual": race._render_race_board(race.HORSES[:4], positions),
                    "events": [f"事件{round_num}"],
                }
            )
        simulation = {"frames": frames, "winner_idx": 3}

        story = race._build_story_frames(simulation, race.HORSES[:4], seed=42)

        self.assertEqual([frame["phase"] for frame in story], list(race.STORY_PHASES))
        self.assertEqual(len(story), 3)
        self.assertEqual(
            [event for frame in story for event in frame["events"]],
            [f"事件{round_num}" for round_num in range(1, 8)],
        )
        self.assertIn("闪电兔兔", story[-1]["commentary"])

    def test_identical_racers_do_not_favor_early_lanes(self):
        runs = 4000
        identical_horses = [dict(race.HORSES[2]) for _ in range(4)]
        wins = Counter(
            race._simulate_race({"horses": identical_horses, "seed": seed})["winner_idx"]
            for seed in range(runs)
        )

        for lane_index in range(4):
            win_rate = wins[lane_index] / runs
            self.assertGreater(win_rate, 0.22)
            self.assertLess(win_rate, 0.28)

    def test_racer_profiles_stay_inside_balance_band(self):
        runs = 4000
        entries = Counter()
        wins = Counter()
        for seed in range(runs):
            horses = random.Random(f"sample:{seed}").sample(race.HORSES, 4)
            result = race._simulate_race({"horses": horses, "seed": seed})
            for horse in horses:
                entries[horse["name"]] += 1
            wins[horses[result["winner_idx"]]["name"]] += 1

        for horse in race.HORSES:
            name = horse["name"]
            win_rate = wins[name] / entries[name]
            self.assertGreater(win_rate, 0.21, name)
            self.assertLess(win_rate, 0.29, name)


if __name__ == "__main__":
    unittest.main()
