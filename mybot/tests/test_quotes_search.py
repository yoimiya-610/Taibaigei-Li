import unittest

import nonebot


nonebot.init()

from mybot.plugins.quotes import MAX_SEARCH_RESULTS, _search_classics, _search_result_block, _trim_text


class QuotesSearchTest(unittest.TestCase):
    def test_search_classics_matches_case_insensitively_and_sorts_newest_first(self):
        records = [
            {
                "speaker_name": "甲",
                "content": "今晚去喝酒",
                "recorded_timestamp": 10,
                "message_time": "2026-06-27 20:00:00",
                "recorded_at": "2026-06-27 20:01:00",
            },
            {
                "speaker_name": "乙",
                "content": "喝酒要配月色",
                "recorded_timestamp": 30,
                "message_time": "2026-06-29 20:00:00",
                "recorded_at": "2026-06-29 20:01:00",
            },
            {
                "speaker_name": "丙",
                "content": "今天只想睡觉",
                "recorded_timestamp": 20,
                "message_time": "2026-06-28 20:00:00",
                "recorded_at": "2026-06-28 20:01:00",
            },
        ]

        matches = _search_classics(records, "喝酒")

        self.assertEqual([record["speaker_name"] for record in matches], ["乙", "甲"])

    def test_search_classics_limits_result_count(self):
        records = [
            {"speaker_name": str(index), "content": "有风", "recorded_timestamp": index}
            for index in range(MAX_SEARCH_RESULTS + 3)
        ]

        matches = _search_classics(records, "有风")

        self.assertEqual(len(matches), MAX_SEARCH_RESULTS)
        self.assertEqual(matches[0]["recorded_timestamp"], MAX_SEARCH_RESULTS + 2)

    def test_search_classics_returns_empty_when_keyword_blank(self):
        self.assertEqual(_search_classics([{"content": "随便"}], "   "), [])

    def test_search_result_block_trims_long_content(self):
        record = {
            "speaker_name": "甲",
            "content": "春" * 120,
            "message_time": "2026-06-29 20:00:00",
            "recorded_at": "2026-06-29 20:01:00",
        }

        block = _search_result_block(1, record)

        self.assertIn("甲｜2026-06-29 20:00:00", block)
        self.assertIn("…", block)
        self.assertLessEqual(len(_trim_text(record["content"])), 80)


if __name__ == "__main__":
    unittest.main()
