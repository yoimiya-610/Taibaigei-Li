import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from mybot.common import group_management as gm
from mybot.common import group_platform as platform
from mybot.common.message_utils import get_first_at_user_id, get_reply_message_id
from mybot.common.onebot_capabilities import (
    Capability,
    CapabilityStatus,
    ImplementationFamily,
    ImplementationInfo,
    onebot_capability_registry,
)


class GroupManagementTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        replacements = {
            "ESSENCE_FILE": root / "essence.json",
            "MESSAGE_FILE": root / "messages.json",
            "CARD_FILE": root / "cards.json",
            "CARD_QUEUE_FILE": root / "card_queue.json",
            "ACTIVITY_FILE": root / "activities.json",
            "ACTIVITY_ARCHIVE_FILE": root / "activity_archive.json",
        }
        self.patches = [patch.object(gm, name, value) for name, value in replacements.items()]
        self.patches.append(patch.object(gm, "is_feature_enabled", return_value=True))
        for item in self.patches:
            item.start()
        gm._poke_times.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_reply_and_at_are_read_from_segments(self):
        message = Message(
            [
                MessageSegment.reply("7788"),
                MessageSegment.at("10001"),
                MessageSegment.text("正文"),
            ]
        )
        self.assertEqual(get_reply_message_id(message), "7788")
        self.assertEqual(get_first_at_user_id(message), "10001")

    def test_reply_id_accepts_segment_order_and_integer_ids(self):
        command_first = Message(
            [
                MessageSegment.text("/加精"),
                MessageSegment("reply", {"id": 7788}),
            ]
        )
        self.assertEqual(get_reply_message_id(command_first), "7788")

    def test_candidates_degrade_and_sort_without_fabricating_likes(self):
        gm.index_message("20001", "1", "10", "甲", "第一句", None, 100)
        gm.index_message("20001", "2", "11", "乙", "第二句", "1", 101)
        gm.index_message("20001", "3", "12", "丙", "第三句", "1", 102)
        candidates = gm.build_candidates("20001")
        first = next(item for item in candidates if item["message_id"] == "1")
        self.assertIsNone(first["likes"])
        self.assertEqual(first["replies"], 2)

        gm.record_emoji_likes("20001", "2", [{"count": 5}])
        self.assertEqual(gm.build_candidates("20001")[0]["message_id"], "2")

    def test_essence_events_are_idempotent_and_remove_candidates(self):
        gm.index_message("20001", "1", "10", "甲", "一句话", None, 100)
        gm.mark_essence_pending("20001", "1", "add")
        gm.sync_essence_event("20001", "1", "add", "10", "20")
        gm.sync_essence_event("20001", "1", "add", "10", "20")
        self.assertEqual(gm.build_candidates("20001"), [])
        gm.sync_essence_event("20001", "1", "delete", "10", "20")
        self.assertEqual(len(gm.build_candidates("20001")), 1)

    def test_weekly_digest_is_read_only_and_separate_from_classics(self):
        now = datetime(2026, 7, 9, 12, 0, 0)
        gm.index_message("20001", "1", "10", "甲", "群聊摘要", None, now.timestamp())
        before = gm.ESSENCE_FILE.exists()
        digest = gm.weekly_digest("20001", now)
        self.assertEqual(digest[0]["text"], "群聊摘要")
        self.assertEqual(gm.ESSENCE_FILE.exists(), before)
        self.assertNotEqual(gm.ESSENCE_FILE.name, "classics.json")

    def test_card_format_authorization_restore_and_queue_cooldown(self):
        record = gm.authorize_card("20001", "10001", "旧名片", "昵称甲", "【称号】昵称")
        self.assertEqual(record["original_card"], "旧名片")
        second = gm.authorize_card("20001", "10001", "不应覆盖", "昵称甲", "{nickname}-{title}")
        self.assertEqual(second["original_card"], "旧名片")
        self.assertEqual(gm.render_card(second["format"], "诗仙\n", "名{字}"), "名字-诗仙")

        due = datetime.now() + timedelta(minutes=2)
        self.assertTrue(gm.queue_card_sync("20001", "10001", due))
        self.assertEqual(gm.due_card_jobs(datetime.now()), [])
        self.assertEqual(len(gm.due_card_jobs(due + timedelta(seconds=1))), 1)
        restored = gm.disable_card("20001", "10001")
        self.assertEqual(restored["original_card"], "旧名片")
        self.assertFalse(gm.queue_card_sync("20001", "10001"))

    def test_invalid_card_queue_job_does_not_block_valid_due_job(self):
        due = datetime.now() - timedelta(seconds=1)
        gm.CARD_QUEUE_FILE.write_text(
            '{"version": 1, "jobs": {'
            '"bad": {"group_id": "1", "user_id": "10", "due_at": "not-a-date"},'
            f'"good": {{"group_id": "2", "user_id": "20", "due_at": "{due.isoformat()}"}}'
            "}}",
            encoding="utf-8",
        )

        self.assertEqual(
            gm.due_card_jobs(datetime.now()),
            [{"group_id": "2", "user_id": "20", "due_at": due.isoformat()}],
        )

    def test_disabled_group_does_not_read_or_write_card_queue_state(self):
        with (
            patch.object(gm, "is_feature_enabled", return_value=False),
            patch.object(gm, "get_card_record") as get_card_record,
        ):
            self.assertFalse(gm.queue_card_sync("20001", "10001"))

        get_card_record.assert_not_called()
        self.assertFalse(gm.CARD_QUEUE_FILE.exists())

    def test_invalid_card_formats_are_rejected_and_length_is_limited(self):
        for value in ("固定文字", "{unknown}{nickname}", "{title}"):
            with self.assertRaises(ValueError):
                gm.normalize_card_format(value)
        card = gm.render_card("{title}{nickname}", "称号" * 30, "昵称" * 30)
        self.assertLessEqual(len(card), gm.MAX_CARD_LENGTH)
        self.assertNotIn("\n", card)

    def test_poke_rate_limit_is_scoped_by_group_and_operator(self):
        now = datetime(2026, 7, 9, 12, 0, 0)
        self.assertTrue(gm.allow_poke("1", "10", now))
        self.assertFalse(gm.allow_poke("1", "10", now + timedelta(seconds=5)))
        self.assertTrue(gm.allow_poke("2", "10", now + timedelta(seconds=5)))
        self.assertTrue(gm.allow_poke("1", "11", now + timedelta(seconds=5)))

    def test_activities_are_group_scoped_and_persist(self):
        gm.create_activity("1", "10", "甲群活动")
        gm.create_activity("2", "20", "乙群活动")
        gm.join_activity("1", "11", "甲")
        gm.join_activity("1", "12", "乙")
        gm.join_activity("2", "21", "丙")
        self.assertEqual(len(gm.get_activity("1")["participants"]), 2)
        self.assertEqual(len(gm.get_activity("2")["participants"]), 1)
        self.assertEqual(gm.get_activity("1")["name"], "甲群活动")

    def test_random_groups_are_reproducible_and_archived(self):
        gm.create_activity("1", "10", "活动")
        for user_id in ("11", "12", "13", "14"):
            gm.join_activity("1", user_id, f"成员{user_id}")
        first = gm.group_activity("1", 2)
        second = gm.group_activity("1", 2)
        self.assertEqual(first, second)
        self.assertTrue(gm.get_activity("1")["seed"])
        gm.finish_activity("1", "finished")
        archived = gm.archive_activity("1")
        self.assertEqual(archived["status"], "finished")
        self.assertIsNone(gm.get_activity("1"))

    def test_activity_validation_and_cancel(self):
        gm.create_activity("1", "10", "活动")
        with self.assertRaisesRegex(ValueError, "activity_exists"):
            gm.create_activity("1", "11", "另一活动")
        with self.assertRaisesRegex(ValueError, "no_participants"):
            gm.group_activity("1", 2)
        result = gm.finish_activity("1", "cancelled")
        self.assertEqual(result["status"], "cancelled")

    def test_activity_deadline_recovers_after_restart_and_archive_cleanup(self):
        now = datetime.now()
        gm.create_activity("1", "10", "计时活动", now)
        gm.set_activity_deadline("1", 1)
        expired = gm.expire_due_activities(now + timedelta(minutes=1))
        self.assertEqual(expired[0][1]["status"], "finished")
        gm.archive_activity("1")
        self.assertEqual(len(gm.list_activity_archives("1")), 1)
        self.assertEqual(gm.clear_activity_archives("1"), 1)
        self.assertEqual(gm.list_activity_archives("1"), [])

    def test_disabled_group_activity_deadline_is_not_mutated(self):
        now = datetime.now()
        gm.create_activity("1", "10", "计时活动", now)
        gm.set_activity_deadline("1", 1)
        before = gm.ACTIVITY_FILE.read_bytes()

        expired = gm.expire_due_activities(
            now + timedelta(minutes=1),
            group_filter=lambda group_id: group_id != "1",
        )

        self.assertEqual(expired, [])
        self.assertEqual(gm.ACTIVITY_FILE.read_bytes(), before)
        self.assertEqual(gm.get_activity("1")["status"], "active")


class GroupPlatformTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        generation = onebot_capability_registry.begin_connection()
        onebot_capability_registry.apply_probe(
            generation,
            ImplementationInfo("NapCat.Onebot", "4.8.95", "v11", ImplementationFamily.NAPCAT),
            healthy=True,
            issue=None,
        )

    async def asyncTearDown(self):
        onebot_capability_registry.mark_disconnected()

    async def test_essence_and_poke_use_documented_actions(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(return_value={})
        await platform.set_essence(bot, "7788")
        bot.call_api.assert_awaited_with("set_essence_msg", message_id="7788")
        await platform.delete_essence(bot, "7788")
        bot.call_api.assert_awaited_with("delete_essence_msg", message_id="7788")
        await platform.group_poke(bot, "20001", "10001")
        bot.call_api.assert_awaited_with("group_poke", group_id="20001", user_id="10001")

    async def test_group_card_uses_napcat_numeric_action_parameters(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(return_value={})
        await platform.set_group_card(bot, "20001", "10001", "新名片")
        bot.call_api.assert_awaited_once_with(
            "set_group_card",
            group_id=20001,
            user_id=10001,
            card="新名片",
        )

    async def test_platform_failure_is_safely_classified(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(side_effect=RuntimeError("private detail"))
        with self.assertRaisesRegex(platform.PlatformOperationError, "unavailable"):
            await platform.set_essence(bot, "7788")
        snapshot = onebot_capability_registry.snapshot()
        self.assertEqual(
            snapshot.capability(Capability.ESSENCE_MESSAGE).status,
            CapabilityStatus.DEGRADED,
        )
        self.assertEqual(
            snapshot.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.SUPPORTED,
        )

    async def test_manager_check_requires_operator_and_bot_roles(self):
        bot = AsyncMock()
        bot.self_id = 999
        bot.call_api = AsyncMock(side_effect=[{"role": "admin"}, {"role": "owner"}])
        await platform.require_platform_managers(bot, "20001", "10001")
        self.assertEqual(bot.call_api.await_count, 2)

        bot.call_api = AsyncMock(return_value={"role": "member"})
        with self.assertRaisesRegex(platform.PlatformOperationError, "operator_not_manager"):
            await platform.require_platform_managers(bot, "20001", "10001")


if __name__ == "__main__":
    unittest.main()
