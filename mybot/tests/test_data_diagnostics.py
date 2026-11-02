from pathlib import Path
import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from mybot.common.config import ImageLibrarySettings, RetentionSettings
from mybot.common.data_health import EXPECTED_SCHEDULED_JOBS, build_system_diagnostic
from mybot.common.help_registry import collect_public_command_names
from mybot.common.onebot_capabilities import (
    OneBotCapabilityRegistry,
    probe_onebot_connection,
)
from mybot.plugins import data_diagnostics
from mybot.plugins.data_diagnostics import (
    render_data_manifest,
    render_group_data_summary,
    render_system_diagnostic,
)


class _Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.next_run_time = object()


class _Scheduler:
    running = True

    def get_jobs(self):
        return [_Job(job_id) for job_id in EXPECTED_SCHEDULED_JOBS]


class _Adapter:
    @staticmethod
    def get_name() -> str:
        return "OneBot V11"


class _Bot:
    adapter = _Adapter()

    def __init__(self, responses):
        self.responses = responses

    async def call_api(self, action: str, **params):
        response = self.responses[action]
        if asyncio.iscoroutine(response):
            return await response
        return response


class _Event:
    def get_user_id(self) -> str:
        return "opaque-user"


class _StopMatcher(Exception):
    pass


class DataDiagnosticsTest(unittest.TestCase):
    def test_group_summary_discloses_switches_and_retention_without_member_details(self):
        retention = RetentionSettings(
            group_chat_log_retention_days=30,
            backup_include_group_chat_logs=False,
            backup_include_image_library=True,
        )
        image_settings = ImageLibrarySettings(
            max_group_bytes=64 * 1024 * 1024,
            max_group_images=120,
        )

        with (
            patch("mybot.plugins.data_diagnostics.get_retention_settings", return_value=retention),
            patch("mybot.plugins.data_diagnostics.get_image_library_settings", return_value=image_settings),
            patch(
                "mybot.plugins.data_diagnostics.is_feature_enabled",
                side_effect=lambda feature, group_id: feature != "image_library",
            ),
        ):
            text = render_group_data_summary("20001")

        self.assertIn("群聊记录", text)
        self.assertIn("保留 30 天，不进入每日备份", text)
        self.assertIn("关｜群聊图片库", text)
        self.assertIn("120 张/64.0 MiB，进入每日备份", text)
        self.assertIn("不展示任何群友明细", text)
        self.assertNotIn("20001", text)

    def test_system_render_and_manifest_explain_read_only_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mybot"
            root.mkdir()
            backup_root = Path(tmp) / "backups"
            report = build_system_diagnostic(
                _Scheduler(),
                bot_root=root,
                backup_root=backup_root,
            )
            text = render_system_diagnostic(report)

        self.assertIn("本次巡检只读", text)
        self.assertIn("付费恢复钩子 在册", text)
        self.assertIn("插件：已加载", text)
        self.assertIn("备份：", text)

        manifest = render_data_manifest()
        self.assertIn("共 28 项", manifest)
        self.assertIn("v1｜JSON｜data/admin_audit.json", manifest)
        self.assertIn("v1｜YAML目录｜data/group_chat_logs", manifest)

    def test_public_command_index_exposes_group_data_but_not_system_diagnostics(self):
        commands = collect_public_command_names()
        self.assertIn("本群数据", commands)
        self.assertNotIn("系统诊断", commands)


class OneBotDataDiagnosticTest(unittest.IsolatedAsyncioTestCase):
    async def test_summary_lists_capabilities_without_raw_sensitive_fields(self):
        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            _Bot(
                {
                    "get_version_info": {
                        "app_name": "NapCat.Onebot",
                        "app_version": "4.8.95",
                        "protocol_version": "v11",
                        "access_token": "forbidden-secret",
                        "websocket_url": "ws://private-endpoint",
                        "self_id": "account-marker",
                        "group_id": "group-marker",
                    },
                    "get_status": {"online": True, "good": True},
                }
            ),
            registry=registry,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mybot"
            root.mkdir()
            report = build_system_diagnostic(
                _Scheduler(),
                bot_root=root,
                backup_root=Path(tmp) / "backups",
            )
            text = render_system_diagnostic(report, snapshot)

        self.assertIn("实现 NapCat.Onebot 4.8.95", text)
        for capability in (
            "名片点赞",
            "群戳一戳",
            "精华消息",
            "图片地址刷新",
            "图片 OCR",
        ):
            self.assertIn(f"能力｜{capability}：可用（supported）", text)
        for secret in (
            "forbidden-secret",
            "private-endpoint",
            "account-marker",
            "group-marker",
            "websocket_url",
            "access_token",
        ):
            self.assertNotIn(secret, text)

    async def test_non_admin_cannot_run_system_diagnostic(self):
        finish = AsyncMock(side_effect=_StopMatcher)
        with (
            patch.object(data_diagnostics, "is_admin_user", return_value=False),
            patch.object(data_diagnostics.system_diagnostic, "finish", finish),
            self.assertRaises(_StopMatcher),
        ):
            await data_diagnostics.handle_system_diagnostic(_Event())

        finish.assert_awaited_once_with("（合上总册）此卷只交系统掌柜过目。")


if __name__ == "__main__":
    unittest.main()
