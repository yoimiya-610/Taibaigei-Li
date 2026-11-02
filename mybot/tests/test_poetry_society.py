import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from nonebot.adapters.onebot.v11 import Message, MessageSegment

import mybot.bot  # noqa: F401
from mybot.common import feature_flags
from mybot.common.admin import get_feature_permission_level
from mybot.common.help_registry import CATEGORY_META, render_category_help, render_help_menu
from mybot.common.json_store import JsonStoreReadError
from mybot.common import poetry_society as society
from mybot.plugins import poetry_society as society_plugin


OPEN = datetime(2026, 7, 13, 12, 0, tzinfo=society.SHANGHAI_TZ)
CUTOFF = datetime(2026, 7, 19, 21, 0, tzinfo=society.SHANGHAI_TZ)
NEXT_WEEK = datetime(2026, 7, 20, 0, 0, tzinfo=society.SHANGHAI_TZ)


class PoetrySocietyDomainTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_path = Path(self.temp_dir.name) / "poetry_society.json"
        self.data_patch = patch.object(society, "DATA_FILE", self.data_path)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)

    def _data(self) -> dict:
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def _settlement(self, group_id: str = "20001", target: str = "2026-W29") -> dict:
        return self._data()["groups"][group_id]["weeks"][target]["settlement"]

    def test_theme_is_stable_for_same_group_and_week(self):
        first = society.get_overview("20001", OPEN)["week"]
        second = society.get_overview("20001", OPEN + timedelta(days=2))["week"]
        self.assertEqual(first["key"], "2026-W29")
        self.assertEqual(first["theme"], second["theme"])
        self.assertEqual(
            first["theme"], society.stable_theme("20001", first["year"], first["week"])
        )

    def test_groups_keep_independent_works_votes_and_ids(self):
        first = society.submit_work("20001", "10001", "甲群诗", now=OPEN)
        second = society.submit_work("20002", "10001", "乙群诗", now=OPEN)
        society.submit_work("20001", "10002", "甲群次诗", now=OPEN)
        society.cast_vote("20001", "10003", first["submission"]["id"], now=OPEN)

        self.assertEqual(first["submission"]["id"], "1")
        self.assertEqual(second["submission"]["id"], "1")
        self.assertEqual([row["content"] for row in society.list_works("20002", OPEN)["works"]], ["乙群诗"])
        data = self._data()
        self.assertEqual(set(data["groups"]), {"20001", "20002"})
        self.assertEqual(data["groups"]["20002"]["weeks"]["2026-W29"]["votes"], {})

    def test_week_state_switches_at_shanghai_cutoff_and_monday(self):
        self.assertEqual(society.get_overview("20001", CUTOFF - timedelta(seconds=1))["week"]["phase"], "open")
        settled = society.get_overview("20001", CUTOFF)["week"]
        following = society.get_overview("20001", NEXT_WEEK)["week"]

        self.assertEqual(settled["phase"], "settled")
        self.assertEqual(settled["settlement"]["outcome"], "no_submissions")
        self.assertEqual(following["key"], "2026-W30")
        self.assertEqual(following["phase"], "open")

    def test_single_active_work_with_withdraw_and_new_stable_id(self):
        first = society.submit_work("20001", "10001", "旧稿", now=OPEN)
        with self.assertRaisesRegex(society.PoetrySocietyError, "duplicate_submission"):
            society.submit_work("20001", "10001", "重复稿", now=OPEN)
        society.cast_vote("20001", "10002", first["submission"]["id"], now=OPEN)
        withdrawn = society.withdraw_work("20001", "10001", now=OPEN)
        second = society.submit_work("20001", "10001", "新稿", now=OPEN)

        self.assertEqual(withdrawn["invalidated_votes"], 1)
        self.assertNotEqual(first["submission"]["id"], second["submission"]["id"])
        self.assertEqual(second["submission"]["id"], "2")
        week = self._data()["groups"]["20001"]["weeks"]["2026-W29"]
        self.assertEqual(week["votes"], {})
        self.assertEqual(week["submissions"]["1"]["status"], "withdrawn")

    def test_text_cleaning_empty_and_visible_length_boundaries(self):
        cleaned = society.clean_submission_text("  甲\x00\n乙\u200b  ")
        self.assertEqual(cleaned, "甲 乙")
        self.assertEqual(society.visible_character_count(cleaned), 2)
        self.assertEqual(len(society.clean_submission_text("月" * 200)), 200)
        for invalid, code in ((" \x00\u200b ", "empty_content"), ("月" * 201, "content_too_long")):
            with self.subTest(code=code):
                with self.assertRaisesRegex(society.PoetrySocietyError, code):
                    society.clean_submission_text(invalid)

    def test_one_vote_per_user_and_safe_vote_change(self):
        first = society.submit_work("20001", "10001", "甲", now=OPEN)["submission"]
        second = society.submit_work("20001", "10002", "乙", now=OPEN)["submission"]
        initial = society.cast_vote("20001", "10003", first["id"], now=OPEN)
        changed = society.cast_vote("20001", "10003", second["id"], now=OPEN)

        self.assertIsNone(initial["previous_submission_id"])
        self.assertTrue(changed["changed"])
        votes = self._data()["groups"]["20001"]["weeks"]["2026-W29"]["votes"]
        self.assertEqual(votes, {"10003": {"submission_id": "2", "voted_at": OPEN.isoformat()}})

    def test_self_vote_is_rejected_without_writing_a_vote(self):
        work = society.submit_work("20001", "10001", "甲", now=OPEN)["submission"]
        with self.assertRaisesRegex(society.PoetrySocietyError, "self_vote"):
            society.cast_vote("20001", "10001", work["id"], now=OPEN)
        self.assertEqual(self._data()["groups"]["20001"]["weeks"]["2026-W29"]["votes"], {})

    def test_invalid_withdrawn_removed_and_old_week_ids_are_rejected(self):
        withdrawn = society.submit_work("20001", "10001", "撤稿", now=OPEN)["submission"]
        society.withdraw_work("20001", "10001", now=OPEN)
        with self.assertRaisesRegex(society.PoetrySocietyError, "inactive_submission"):
            society.cast_vote("20001", "10002", withdrawn["id"], now=OPEN)

        removed = society.submit_work("20001", "10003", "移除稿", now=OPEN)["submission"]
        society.remove_work("20001", removed["id"], "90001", now=OPEN)
        with self.assertRaisesRegex(society.PoetrySocietyError, "inactive_submission"):
            society.cast_vote("20001", "10002", removed["id"], now=OPEN)
        with self.assertRaisesRegex(society.PoetrySocietyError, "missing_submission"):
            society.cast_vote("20001", "10002", "999", now=OPEN)

        society.get_overview("20001", CUTOFF)
        current = society.submit_work("20001", "10004", "新周稿", now=NEXT_WEEK)["submission"]
        self.assertEqual(current["id"], "3")
        with self.assertRaisesRegex(society.PoetrySocietyError, "old_submission"):
            society.cast_vote("20001", "10002", removed["id"], now=NEXT_WEEK)

    def test_admin_removal_invalidates_all_related_votes(self):
        work = society.submit_work("20001", "10001", "待移除", now=OPEN)["submission"]
        society.cast_vote("20001", "10002", work["id"], now=OPEN)
        society.cast_vote("20001", "10003", work["id"], now=OPEN)
        result = society.remove_work("20001", work["id"], "90001", now=OPEN)

        self.assertEqual(result["invalidated_votes"], 2)
        week = self._data()["groups"]["20001"]["weeks"]["2026-W29"]
        self.assertEqual(week["votes"], {})
        self.assertEqual(week["submissions"][work["id"]]["removed_by"], "90001")

    def test_live_votes_are_hidden_until_settlement(self):
        first = society.submit_work("20001", "10001", "甲", now=OPEN)["submission"]
        society.submit_work("20001", "10002", "乙", now=OPEN)
        society.cast_vote("20001", "10003", first["id"], now=OPEN)

        live = society.list_works("20001", OPEN)
        self.assertTrue(all("votes" not in work for work in live["works"]))
        final = society.list_works("20001", CUTOFF)
        self.assertEqual(final["works"][0]["votes"], 1)
        self.assertEqual(final["week"]["phase"], "settled")

    def test_ranking_uses_votes_then_submission_time_then_id(self):
        same_time = OPEN
        first = society.submit_work("20001", "10001", "甲", now=same_time)["submission"]
        second = society.submit_work("20001", "10002", "乙", now=same_time)["submission"]
        third = society.submit_work("20001", "10003", "丙", now=OPEN + timedelta(minutes=1))["submission"]
        society.cast_vote("20001", "11001", second["id"], now=OPEN)
        society.cast_vote("20001", "11002", first["id"], now=OPEN)
        society.cast_vote("20001", "11003", third["id"], now=OPEN)
        society.cast_vote("20001", "11004", third["id"], now=OPEN)

        society.get_overview("20001", CUTOFF)
        rankings = self._settlement()["rankings"]
        self.assertEqual([item["id"] for item in rankings], ["3", "1", "2"])
        self.assertEqual([item["votes"] for item in rankings], [2, 1, 1])

    def test_settlement_is_idempotent_and_history_is_unique(self):
        society.submit_work("20001", "10001", "甲", now=OPEN)
        first = society.get_overview("20001", CUTOFF)["week"]["settlement"]
        second = society.get_overview("20001", CUTOFF + timedelta(hours=1))["week"]["settlement"]
        recovered = society.recover_all_due(CUTOFF + timedelta(hours=2))

        self.assertEqual(first, second)
        self.assertEqual(recovered, [])
        self.assertEqual(self._data()["groups"]["20001"]["history"], ["2026-W29"])

    def test_no_submission_and_no_vote_outcomes_are_explicit(self):
        society.get_overview("20001", OPEN)
        society.submit_work("20002", "10001", "有稿无票", now=OPEN)
        society.recover_all_due(CUTOFF)

        self.assertEqual(self._settlement("20001")["outcome"], "no_submissions")
        self.assertEqual(self._settlement("20002")["outcome"], "no_votes")
        self.assertEqual(self._settlement("20002")["rankings"][0]["votes"], 0)

    def test_restart_and_missed_weeks_are_recovered_from_persisted_state(self):
        society.get_overview("20001", OPEN)
        week_three = datetime(2026, 7, 27, 0, 0, tzinfo=society.SHANGHAI_TZ)
        recovered = society.recover_all_due(week_three)
        data = self._data()["groups"]["20001"]

        self.assertEqual(
            [item["week_key"] for item in recovered],
            ["2026-W29", "2026-W30"],
        )
        self.assertEqual(set(data["weeks"]), {"2026-W29", "2026-W30", "2026-W31"})
        self.assertEqual(data["weeks"]["2026-W30"]["settlement"]["outcome"], "no_submissions")
        self.assertNotIn("settlement", data["weeks"]["2026-W31"])

    def test_empty_object_and_missing_optional_fields_are_upgraded(self):
        self.data_path.write_text("{}", encoding="utf-8")
        overview = society.get_overview("20001", OPEN)
        data = self._data()

        self.assertEqual(overview["week"]["key"], "2026-W29")
        self.assertEqual(data["schema_version"], society.SCHEMA_VERSION)
        self.assertEqual(data["groups"]["20001"]["next_submission_id"], 1)

    def test_existing_week_with_missing_optional_fields_can_be_settled(self):
        self.data_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "groups": {
                        "20001": {
                            "weeks": {"2026-W29": {"submissions": {}, "votes": {}}}
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        result = society.get_overview("20001", CUTOFF)
        week = self._data()["groups"]["20001"]["weeks"]["2026-W29"]

        self.assertEqual(result["week"]["settlement"]["outcome"], "no_submissions")
        self.assertEqual(week["year"], 2026)
        self.assertEqual(week["week"], 29)
        self.assertTrue(week["theme"])

    def test_damaged_json_is_never_overwritten(self):
        original = '{"schema_version": 1, "broken":'
        self.data_path.write_text(original, encoding="utf-8")
        with self.assertRaises(JsonStoreReadError):
            society.get_overview("20001", OPEN)
        self.assertEqual(self.data_path.read_text(encoding="utf-8"), original)

    def test_notification_claim_is_at_most_once_and_does_not_change_result(self):
        society.submit_work("20001", "10001", "甲", now=OPEN)
        society.get_overview("20001", CUTOFF)
        before = copy_without_notification(self._settlement())

        claimed = society.claim_notification("20001", "2026-W29", now=CUTOFF)
        self.assertIsNotNone(claimed)
        self.assertIsNone(society.claim_notification("20001", "2026-W29", now=CUTOFF))
        self.assertTrue(society.finish_notification("20001", "2026-W29", success=False, now=CUTOFF))
        self.assertFalse(society.finish_notification("20001", "2026-W29", success=True, now=CUTOFF))
        self.assertEqual(copy_without_notification(self._settlement()), before)
        self.assertEqual(self._settlement()["notification"]["status"], "failed")

    def test_concurrent_same_author_submissions_leave_one_active_work(self):
        def attempt(index: int) -> str:
            try:
                return society.submit_work("20001", "10001", f"稿{index}", now=OPEN)["submission"]["id"]
            except society.PoetrySocietyError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(attempt, range(20)))

        self.assertEqual(sum(item.isdigit() for item in outcomes), 1)
        self.assertEqual(outcomes.count("duplicate_submission"), 19)
        works = society.list_works("20001", OPEN)["works"]
        self.assertEqual(len(works), 1)

    def test_concurrent_vote_changes_leave_one_valid_vote(self):
        first = society.submit_work("20001", "10001", "甲", now=OPEN)["submission"]
        second = society.submit_work("20001", "10002", "乙", now=OPEN)["submission"]

        def vote(index: int) -> None:
            target = first["id"] if index % 2 == 0 else second["id"]
            society.cast_vote("20001", "10003", target, now=OPEN)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(vote, range(40)))

        votes = self._data()["groups"]["20001"]["weeks"]["2026-W29"]["votes"]
        self.assertEqual(set(votes), {"10003"})
        self.assertIn(votes["10003"]["submission_id"], {"1", "2"})

    def test_submission_and_settlement_race_remains_consistent(self):
        society.submit_work("20001", "10001", "底稿", now=OPEN)

        def late_submit():
            try:
                society.submit_work(
                    "20001",
                    "10002",
                    "临界稿",
                    now=CUTOFF - timedelta(seconds=1),
                )
                return "submitted"
            except society.PoetrySocietyError as exc:
                return exc.code

        def settle():
            society.get_overview("20001", CUTOFF)
            return "settled"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda fn: fn(), (late_submit, settle)))

        settlement = self._settlement()
        self.assertIn(outcomes[0], {"submitted", "closed"})
        self.assertEqual(outcomes[1], "settled")
        self.assertIn(settlement["total_submissions"], {1, 2})
        self.assertEqual(self._data()["groups"]["20001"]["history"], ["2026-W29"])


class PoetrySocietyIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_path = Path(self.temp_dir.name) / "poetry_society.json"
        self.data_patch = patch.object(society, "DATA_FILE", self.data_path)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)

    def test_overview_introduces_society_and_uses_one_command_per_line(self):
        overview = society_plugin._render_overview(
            {
                "phase": "open",
                "cutoff_at": CUTOFF.isoformat(),
                "year": 2026,
                "week": 29,
                "theme": "月下故人",
                "active_submissions": 2,
            }
        )

        self.assertLess(overview.index("本诗社每周悬一题"), overview.index("周次："))
        self.assertIn("每人每周一稿、一票，可在截卷前改投；不可自投。", overview)
        self.assertIn("『一题邀来千家句，周末同看月下章。』", overview)
        self.assertEqual(
            [line for line in overview.splitlines() if line.startswith("/诗社")],
            [
                "/诗社 投稿 <内容>",
                "/诗社 作品",
                "/诗社 投票 <编号>",
                "/诗社 撤稿",
                "/诗社 往卷",
                "/诗社 移除 <编号>（群管理）",
            ],
        )
        self.assertNotIn("/诗社 投稿 <内容>｜", overview)

    def test_help_is_nested_under_poetry_without_new_root_category(self):
        category = render_category_help("诗词文艺")
        root = render_help_menu()

        self.assertIsNotNone(category)
        self.assertIn("/诗社 - 每周主题投稿与投票", category)
        self.assertNotIn("群诗社", CATEGORY_META)
        self.assertNotIn("【群诗社】", root)
        self.assertIn("/游戏 - 查看历史小游戏玩法与开关", render_category_help("趣味功能"))

    def test_feature_flag_aliases_and_plugin_loading_are_registered(self):
        flags_path = Path(self.temp_dir.name) / "feature_flags.json"
        with patch.object(feature_flags, "FEATURE_FLAGS_FILE", flags_path):
            self.assertTrue(feature_flags.DEFAULT_FEATURE_ENABLED["poetry_society"])
            self.assertTrue(feature_flags.is_feature_enabled("poetry_society", "20001"))
            feature_flags.set_feature_enabled("poetry_society", False, "20001")
            self.assertFalse(feature_flags.is_feature_enabled("poetry_society", "20001"))
            self.assertTrue(feature_flags.is_feature_enabled("poetry_society", "20002"))
            self.assertEqual(feature_flags.resolve_feature("群诗社"), "poetry_society")

        import nonebot

        loaded = {plugin.module_name for plugin in nonebot.get_loaded_plugins()}
        self.assertIn("mybot.plugins.poetry_society", loaded)
        self.assertEqual(society_plugin.COMMAND_ALIASES, ("诗社", "群诗社"))
        self.assertEqual(get_feature_permission_level("poetry_society"), 2)

        other_aliases = set()
        for module_name, module in sys.modules.items():
            if not module_name.startswith("mybot.plugins.") or module is society_plugin:
                continue
            other_aliases.update(getattr(module, "COMMAND_ALIASES", ()))
        self.assertTrue(set(society_plugin.COMMAND_ALIASES).isdisjoint(other_aliases))

    def test_command_arguments_reject_non_text_submission_segments(self):
        text = Message([MessageSegment.text("投稿 明月")])
        mixed = Message([MessageSegment.text("投稿 明月"), MessageSegment.image("https://example.com/a.png")])
        self.assertTrue(society_plugin._is_text_only(text))
        self.assertFalse(society_plugin._is_text_only(mixed))

    def test_weekly_job_uses_shanghai_timezone(self):
        job = society_plugin.scheduler.get_job("poetry_society_weekly_settlement")
        self.assertIsNotNone(job)
        self.assertEqual(str(job.trigger.timezone), "Asia/Shanghai")

    def test_notification_failure_preserves_settlement_and_is_not_retried(self):
        society.submit_work("20001", "10001", "甲", now=OPEN)
        society.get_overview("20001", CUTOFF)
        before = copy_without_notification(
            json.loads(self.data_path.read_text(encoding="utf-8"))["groups"]["20001"]["weeks"]["2026-W29"]["settlement"]
        )
        bot = SimpleNamespace(
            send_group_msg=AsyncMock(side_effect=RuntimeError("network down"))
        )

        asyncio.run(society_plugin._publish_pending_notifications(bot, "20001"))
        asyncio.run(society_plugin._publish_pending_notifications(bot, "20001"))

        after = json.loads(self.data_path.read_text(encoding="utf-8"))["groups"]["20001"]["weeks"]["2026-W29"]["settlement"]
        self.assertEqual(copy_without_notification(after), before)
        self.assertEqual(after["notification"]["status"], "failed")
        self.assertEqual(bot.send_group_msg.await_count, 1)


def copy_without_notification(settlement: dict) -> dict:
    copied = json.loads(json.dumps(settlement, ensure_ascii=False))
    copied.pop("notification", None)
    return copied


if __name__ == "__main__":
    unittest.main()
