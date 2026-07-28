import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401

from mybot.common.help_registry import collect_help_items
from mybot.common.onebot_capabilities import (
    OneBotCapabilityRegistry,
    probe_onebot_connection,
)
from mybot.plugins import onebot_diagnostics
from mybot.plugins.onebot_diagnostics import render_system_diagnostic

class StopMatcher(Exception):
    pass


class FakeEvent:
    def get_user_id(self) -> str:
        return "opaque-user"


class FakeAdapter:
    @staticmethod
    def get_name() -> str:
        return "OneBot V11"


class FakeBot:
    adapter = FakeAdapter()

    def __init__(self, responses):
        self.responses = responses

    async def call_api(self, action: str, **params):
        response = self.responses[action]
        if asyncio.iscoroutine(response):
            return await response
        return response


def version_info(app_name: str, app_version: str = "1.2.3") -> dict:
    return {
        "app_name": app_name,
        "app_version": app_version,
        "protocol_version": "v11",
    }


def healthy_status() -> dict:
    return {"online": True, "good": True}


class OneBotDiagnosticTest(unittest.IsolatedAsyncioTestCase):
    async def test_summary_contains_capabilities_without_raw_sensitive_fields(self):
        registry = OneBotCapabilityRegistry()
        raw_version = version_info("NapCat.Onebot", "4.8.95")
        raw_version.update(
            {
                "access_token": "forbidden-secret",
                "websocket_url": "ws://private-endpoint",
                "self_id": "account-marker",
                "group_id": "group-marker",
            }
        )
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": raw_version,
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )

        rendered = render_system_diagnostic(snapshot)

        self.assertIn("NapCat.Onebot 4.8.95", rendered)
        self.assertIn("名片点赞：可用（supported）", rendered)
        self.assertIn("群戳一戳：可用（supported）", rendered)
        self.assertIn("精华消息：可用（supported）", rendered)
        self.assertIn("图片地址刷新：可用（supported）", rendered)
        self.assertIn("图片 OCR：可用（supported）", rendered)
        for secret in (
            "forbidden-secret",
            "private-endpoint",
            "account-marker",
            "group-marker",
            "websocket_url",
            "access_token",
        ):
            self.assertNotIn(secret, rendered)

    async def test_non_admin_cannot_view_summary(self):
        finish = AsyncMock(side_effect=StopMatcher)
        with (
            patch.object(onebot_diagnostics, "is_admin_user", return_value=False),
            patch.object(onebot_diagnostics.system_diagnostic, "finish", finish),
            self.assertRaises(StopMatcher),
        ):
            await onebot_diagnostics.handle_system_diagnostic(FakeEvent())

        finish.assert_awaited_once_with("（合上诊脉簿）此页只交系统掌柜过目。")

    async def test_admin_receives_sanitized_summary(self):
        finish = AsyncMock(side_effect=StopMatcher)
        with (
            patch.object(onebot_diagnostics, "is_admin_user", return_value=True),
            patch.object(onebot_diagnostics.system_diagnostic, "finish", finish),
            self.assertRaises(StopMatcher),
        ):
            await onebot_diagnostics.handle_system_diagnostic(FakeEvent())

        rendered = finish.await_args.args[0]
        self.assertIn("李太白给·系统诊断", rendered)

    def test_admin_only_command_is_not_listed_in_public_help(self):
        self.assertTrue(onebot_diagnostics.HELP_ITEMS[0].system_admin_only)
        public_texts = {item.text for _, _, item in collect_help_items()}
        self.assertNotIn("/系统诊断 - 查看 OneBot 连接与能力摘要", public_texts)


if __name__ == "__main__":
    unittest.main()
