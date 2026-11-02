import copy
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mybot.bot  # noqa: F401
from nonebot.exception import FinishedException

from mybot.common import streak
from mybot.common.accounting import ASSET_POINTS, credit_balance, get_balance, spend_points
from mybot.common.json_store import load_json, save_json
from mybot.common.paid_rounds import PaidRoundService
from mybot.common.usage_policy import PaidOperationService
from mybot.plugins import fortune
from mybot.plugins._fortune.storage import format_makeup_dates, plan_makeup_dates


def signed_data(*days, longest=0):
    data = copy.deepcopy(streak.DEFAULT_FORTUNE_DATA)
    for day in days:
        data["fortune_record"][streak.fortune_record_key(day, "u1", "g1")] = {}
    if longest:
        data["streak"]["g1_u1"] = {"count": 0, "last_date": "", "longest": longest}
    return data


class MakeupPlanTest(unittest.TestCase):
    def test_fills_multiple_gaps_and_preserves_naturally_longer_chain(self):
        data = signed_data("2026-06-30", "2026-06-28", "2026-06-26", "2026-06-25", longest=4)
        plan = plan_makeup_dates(data, "u1", "g1", date(2026, 6, 30))
        self.assertEqual(plan["target_dates"], ["2026-06-27", "2026-06-29"])
        self.assertEqual(plan["restored_streak"], 6)
        self.assertEqual(plan["historical_longest"], 4)
        self.assertEqual(format_makeup_dates(plan["target_dates"]), "2026-06-27、2026-06-29")

    def test_no_history_starts_with_latest_missing_day(self):
        plan = plan_makeup_dates(signed_data(), "u1", "g1", date(2026, 6, 30))
        self.assertEqual(plan["target_dates"], ["2026-06-29"])
        self.assertEqual(plan["restored_streak"], 1)
        self.assertEqual(plan["historical_longest"], 0)

    def test_unsigned_today_ends_at_yesterday(self):
        data = signed_data("2026-06-27", longest=4)
        plan = plan_makeup_dates(data, "u1", "g1", date(2026, 6, 30))
        self.assertEqual(plan["target_dates"], ["2026-06-26", "2026-06-28", "2026-06-29"])
        self.assertEqual(plan["restored_streak"], 4)
        self.assertNotIn("2026-06-30", plan["target_dates"])

    def test_already_beyond_old_record_still_repairs_latest_gap(self):
        data = signed_data("2026-06-30", "2026-06-29", "2026-06-28", "2026-06-26", longest=2)
        plan = plan_makeup_dates(data, "u1", "g1", date(2026, 6, 30))
        self.assertEqual(plan["historical_longest"], 3)
        self.assertEqual(plan["target_dates"], ["2026-06-27"])
        self.assertEqual(plan["restored_streak"], 5)

    def test_year_limit_refuses_unreachable_record(self):
        for today in (date(2026, 1, 1), date(2026, 1, 5)):
            with self.subTest(today=today):
                plan = plan_makeup_dates(signed_data(longest=10), "u1", "g1", today)
                self.assertEqual(plan["status"], "limited")
                self.assertEqual(plan["restored_streak"], today.day - 1)
                self.assertTrue(all(day.startswith("2026-") for day in plan["target_dates"]))

    def test_existing_previous_year_days_can_be_connected(self):
        data = signed_data("2026-01-03", "2025-12-31", "2025-12-30", longest=4)
        plan = plan_makeup_dates(data, "u1", "g1", date(2026, 1, 3))
        self.assertEqual(plan["status"], "available")
        self.assertEqual(plan["target_dates"], ["2026-01-01", "2026-01-02"])
        self.assertEqual(plan["restored_streak"], 5)
        self.assertEqual(format_makeup_dates(plan["target_dates"]), "2026-01-01 至 2026-01-02")

    def test_no_missing_days_this_year(self):
        data = signed_data("2026-01-01", "2026-01-02")
        self.assertEqual(plan_makeup_dates(data, "u1", "g1", date(2026, 1, 2))["status"], "none")

    def test_legacy_records_preserve_longest_after_break_and_restart(self):
        data = signed_data("2025-12-30", "2025-12-31", "2026-01-01")
        data["makeup_records"]["g1_u1"] = {"dates": ["2025-12-29", "2025-12-29"]}
        self.assertEqual(streak.calculate_longest_streak(data, "u1", "g1"), 4)
        data["streak"]["g1_u1"] = {"count": 8, "last_date": "2026-01-01"}
        streak.sync_streak(data, "u1", "g1", date(2026, 6, 30))
        self.assertEqual(data["streak"]["g1_u1"]["count"], 0)
        self.assertEqual(data["streak"]["g1_u1"]["longest"], 8)
        with TemporaryDirectory() as directory:
            file = Path(directory) / "fortune.json"
            save_json(file, data)
            reloaded = load_json(file, {})
        streak.sync_streak(reloaded, "u1", "g1", date(2027, 1, 1))
        self.assertEqual(reloaded["streak"]["g1_u1"]["longest"], 8)

    def test_legacy_record_count_is_retained_and_groups_are_isolated(self):
        data = signed_data("2026-06-01")
        data["fortune_record"]["2026-06-01_g1_u1"]["streak_count"] = 12
        data["fortune_record"]["2026-06-02_g2_u1"] = {"streak_count": 100}
        data["fortune_record"]["2026-06-03_g1_u2"] = {"streak_count": 200}
        data["fortune_record"]["2030-01-01_g1_u1"] = {"streak_count": 300}
        self.assertEqual(streak.calculate_longest_streak(data, "u1", "g1", date(2026, 6, 30)), 12)


class MakeupPaymentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data_file = root / "fortune.json"
        self.points_file = root / "points.json"
        self.service = PaidOperationService(PaidRoundService(
            root / "rounds.json", ledger_paths={ASSET_POINTS: self.points_file},
        ))
        credit_balance("seed", ASSET_POINTS, "u1", "g1", 100, "test", store_path=self.points_file)
        self.data = signed_data("2026-06-30", "2026-06-28", "2026-06-26", "2026-06-25", longest=4)
        self.today_key = "2026-06-30_g1_u1"
        self.data["fortune_record"][self.today_key] = {
            "streak_count": 1, "total_points": 35, "points_awarded": True,
            "streak_multiplier": 10, "award_tx_id": "original",
        }
        save_json(self.data_file, self.data)
        self.now = datetime(2026, 6, 30, 12, tzinfo=fortune.APP_TIMEZONE)
        self.finish = AsyncMock(side_effect=FinishedException)
        self.event = Mock(spec=fortune.GroupMessageEvent)
        self.event.group_id = "g1"
        self.event.get_user_id.return_value = "u1"
        patches = [
            patch.object(fortune, "DATA_FILE", self.data_file),
            patch.object(streak, "DATA_FILE", self.data_file),
            patch.object(fortune, "current_datetime", side_effect=lambda: self.now),
            patch.object(fortune, "PaidOperationService", return_value=self.service),
            patch.object(fortune, "get_points", side_effect=lambda *args: {"current": self.balance()}),
            patch.object(fortune.makeup, "finish", self.finish),
            patch.object(fortune, "get_nickname", AsyncMock(return_value="测试群友")),
            patch.object(fortune, "_format_titled_nickname", return_value="测试群友"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def balance(self):
        return get_balance(ASSET_POINTS, "u1", "g1", store_path=self.points_file)

    def saved(self):
        return load_json(self.data_file, {})

    async def request(self):
        with self.assertRaises(FinishedException):
            await fortune.handle_makeup(Mock(), self.event)
        return self.finish.call_args.args[0]

    async def test_batch_confirmation_charges_once_and_does_not_reaward_points(self):
        confirmation = await self.request()
        self.assertIn("本次共补：2 天", confirmation)
        self.assertIn("整次所需积分：10", confirmation)
        self.assertIn("补后连续签到：6 天", confirmation)
        self.assertEqual(self.balance(), 100)
        success = await self.request()
        self.assertIn("补签成功", success)
        saved = self.saved()
        self.assertEqual(self.balance(), 90)
        self.assertEqual(saved["makeup_usage"]["2026_g1_u1"]["count"], 1)
        self.assertEqual(saved["makeup_records"]["g1_u1"]["dates"], ["2026-06-27", "2026-06-29"])
        self.assertEqual(saved["streak"]["g1_u1"]["longest"], 6)
        self.assertEqual(saved["fortune_record"][self.today_key]["streak_count"], 6)
        for field in ("total_points", "streak_multiplier", "award_tx_id", "points_awarded"):
            self.assertEqual(saved["fortune_record"][self.today_key][field], self.data["fortune_record"][self.today_key][field])
        self.assertEqual(set(saved["fortune_record"]), set(self.data["fortune_record"]))
        next_confirmation = await self.request()
        self.assertIn("整次所需积分：20", next_confirmation)
        self.assertEqual(self.balance(), 90)

    async def test_unreachable_record_does_not_charge_or_write(self):
        self.now = self.now.replace(month=1, day=3)
        save_json(self.data_file, signed_data(longest=10))
        before = self.saved()
        message = await self.request()
        self.assertIn("最多可续至 2 天", message)
        self.assertIn("不收", message)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.service.round_service.list_rounds(), [])

    async def test_state_change_before_confirmation_requires_new_confirmation(self):
        await self.request()
        changed = self.saved()
        changed["fortune_record"]["2026-06-29_g1_u1"] = {}
        save_json(self.data_file, changed)
        message = await self.request()
        self.assertIn("补签确认", message)
        self.assertIn("本次共补：1 天", message)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved(), changed)

    async def test_midnight_requires_new_confirmation_even_when_cost_unchanged(self):
        await self.request()
        self.now += timedelta(days=1)
        self.assertIn("补签确认", await self.request())
        self.assertEqual(self.balance(), 100)

    async def test_plan_change_after_charge_is_refunded_atomically(self):
        await self.request()
        original_confirm = self.service.confirm

        def confirm_and_change(*args, **kwargs):
            result = original_confirm(*args, **kwargs)
            changed = self.saved()
            changed["fortune_record"]["2026-06-29_g1_u1"] = {}
            save_json(self.data_file, changed)
            return result

        with patch.object(self.service, "confirm", side_effect=confirm_and_change):
            message = await self.request()
        self.assertIn("积分已退回", message)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved()["makeup_usage"], {})
        self.assertEqual(self.saved()["makeup_records"], {})

    async def test_write_failure_refunds_and_leaves_dates_and_usage_unchanged(self):
        await self.request()
        with patch.object(fortune, "_apply_makeup", side_effect=OSError("test write failure")):
            message = await self.request()
        self.assertIn("原样归还", message)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved(), self.data)

    async def test_confirmation_expires_after_sixty_seconds(self):
        await self.request()
        with patch("mybot.common.usage_policy.time.time", return_value=time.time() + 61):
            self.assertIn("确认已经过时", await self.request())
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved(), self.data)

    async def test_balance_is_checked_again_at_confirmation(self):
        await self.request()
        with patch.object(fortune, "get_points", return_value={"current": 0}):
            self.assertIn("暂时补不起", await self.request())
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.saved(), self.data)

    async def test_balance_spent_between_precheck_and_charge_does_not_apply(self):
        await self.request()
        original_confirm = self.service.confirm

        def spend_before_charge(*args, **kwargs):
            spend_points("u1", "g1", 100, store_path=self.points_file)
            return original_confirm(*args, **kwargs)

        with patch.object(self.service, "confirm", side_effect=spend_before_charge):
            self.assertIn("确认时账上只余 0 积分", await self.request())
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.saved(), self.data)

    async def test_unsigned_today_remains_unsigned_and_history_survives_next_signin(self):
        del self.data["fortune_record"][self.today_key]
        save_json(self.data_file, self.data)
        await self.request()
        self.assertIn("补签成功", await self.request())
        saved = self.saved()
        self.assertNotIn(self.today_key, saved["fortune_record"])
        self.assertEqual(saved["streak"]["g1_u1"]["count"], 5)
        self.assertEqual(saved["streak"]["g1_u1"]["longest"], 5)
        saved["fortune_record"][self.today_key] = {}
        self.assertEqual(streak.sync_streak(saved, "u1", "g1", self.now.date()), 6)
        self.assertEqual(saved["streak"]["g1_u1"]["longest"], 6)

    async def test_concurrent_confirmation_and_retry_do_not_apply_twice(self):
        plan = fortune.get_makeup_plan("u1", "g1")
        key = fortune._makeup_request_key(plan)
        await self.request()
        original_confirm = self.service.confirm

        def another_request_confirms_first(*args, **kwargs):
            original_confirm(*args, **kwargs)
            return original_confirm(*args, **kwargs)

        with patch.object(self.service, "confirm", side_effect=another_request_confirms_first):
            self.assertIn("不会重扣", await self.request())
        self.assertEqual(self.balance(), 90)
        self.assertEqual(self.saved(), self.data)
        self.assertIn("不会重扣", await self.request())
        self.assertEqual(fortune._apply_makeup("u1", "g1", 10, key)["status"], "created")
        self.assertEqual(fortune._apply_makeup("u1", "g1", 10, key)["status"], "cost_changed")
        self.assertEqual(self.saved()["makeup_usage"]["2026_g1_u1"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
