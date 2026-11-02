from datetime import datetime, timezone
import logging
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nonebot.consts import CMD_KEY, PREFIX_KEY
from nonebot.matcher import current_event, current_matcher

from mybot.common.logger import (
    OBSERVABILITY_STATE_KEY,
    ObservabilityFilter,
    RedactingFormatter,
    get_logger,
    mask_identifier,
    redact_sensitive_text,
)
from mybot.common.observability import (
    _observe_run_finish,
    _observe_run_start,
    new_business_id,
)


class FakeMessageEvent:
    group_id = 1234567890

    def get_type(self) -> str:
        return "message"

    def get_user_id(self) -> str:
        return "9876543210"

    def get_plaintext(self) -> str:
        return "/积分"


class ObservabilityTest(unittest.TestCase):
    def test_loggers_share_one_rotating_file_handler(self):
        first = get_logger("test.observability.first")
        second = get_logger("test.observability.second")
        shared_handlers = set(first.handlers).intersection(second.handlers)
        self.assertEqual(len(shared_handlers), 1)

    def test_business_id_is_timestamped_and_bounded(self):
        value = new_business_id(
            now=datetime(2026, 7, 16, 8, 9, 10, tzinfo=timezone.utc),
            entropy="a1b2c3d4",
        )
        self.assertEqual(value, "TB-20260716080910-a1b2c3d4")

    def test_identifier_mask_keeps_only_correlation_edges(self):
        self.assertEqual(mask_identifier("1234567890"), "123****890")
        self.assertEqual(mask_identifier("123456"), "12**56")
        self.assertEqual(mask_identifier("1234"), "****")
        self.assertEqual(mask_identifier(None), "-")

    def test_sensitive_text_redacts_secrets_and_personal_ids(self):
        rendered = redact_sensitive_text(
            "DEEPSEEK_API_KEY=sk-live Authorization: Bearer token-value "
            "user_id=1234567890 group_id='9876543210'"
        )
        self.assertNotIn("sk-live", rendered)
        self.assertNotIn("token-value", rendered)
        self.assertNotIn("1234567890", rendered)
        self.assertNotIn("9876543210", rendered)
        self.assertIn("123****890", rendered)
        self.assertIn("987****210", rendered)

    def test_filter_adds_masked_event_and_business_context(self):
        event = FakeMessageEvent()
        matcher = SimpleNamespace(
            state={
                OBSERVABILITY_STATE_KEY: {
                    "business_id": "TB-20260716080910-a1b2c3d4",
                    "command": "/积分",
                }
            }
        )
        event_token = current_event.set(event)
        matcher_token = current_matcher.set(matcher)
        try:
            record = logging.LogRecord(
                "test",
                logging.INFO,
                __file__,
                1,
                "request token=%s user_id=%s",
                ("private-token", "1234567890"),
                None,
            )
            record.group_id = "1234567890"
            self.assertTrue(ObservabilityFilter().filter(record))
            output = RedactingFormatter(
                "%(business_id)s %(command)s %(group_id)s %(user_id)s %(message)s"
            ).format(record)
        finally:
            current_matcher.reset(matcher_token)
            current_event.reset(event_token)

        self.assertIn("TB-20260716080910-a1b2c3d4", output)
        self.assertIn("/积分", output)
        self.assertIn("123****890", output)
        self.assertIn("987****210", output)
        self.assertNotIn("private-token", output)
        self.assertNotIn("1234567890", output)
        self.assertNotIn("9876543210", output)

    def test_formatter_redacts_exception_text(self):
        try:
            raise RuntimeError("token=private-token user_id=1234567890")
        except RuntimeError:
            record = logging.LogRecord(
                "test",
                logging.ERROR,
                __file__,
                1,
                "failed",
                (),
                sys.exc_info(),
            )
        ObservabilityFilter().filter(record)
        output = RedactingFormatter(
            "%(business_id)s %(event_type)s %(command)s %(group_id)s %(user_id)s %(message)s"
        ).format(record)
        self.assertNotIn("private-token", output)
        self.assertNotIn("1234567890", output)
        self.assertIn("123****890", output)


class CommandLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_command_lifecycle_records_duration_without_arguments(self):
        matcher = SimpleNamespace(state={}, module_name="mybot.plugins.points")
        event = FakeMessageEvent()
        state = {PREFIX_KEY: {CMD_KEY: ("积分",)}}

        with (
            patch("mybot.common.observability.new_business_id", return_value="TB-test"),
            patch("mybot.common.observability.perf_counter", side_effect=(10.0, 10.125)),
            patch("mybot.common.observability.logger.info") as info,
        ):
            await _observe_run_start(matcher, event, state)
            await _observe_run_finish(matcher)

        observation = matcher.state[OBSERVABILITY_STATE_KEY]
        self.assertEqual(observation["business_id"], "TB-test")
        self.assertEqual(observation["command"], "/积分")
        self.assertEqual(observation["handler"], "points")
        info.assert_any_call("command_started handler=%s", "points")
        info.assert_any_call(
            "command_completed status=%s duration_ms=%.2f handler=%s exception=%s",
            "ok",
            125.0,
            "points",
            "-",
        )


if __name__ == "__main__":
    unittest.main()
