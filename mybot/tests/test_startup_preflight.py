from io import StringIO
import inspect
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from mybot.common.startup_preflight import (
    CheckResult,
    PREFLIGHT_EXIT_CODE,
    PreflightReport,
    Severity,
    check_startup_configuration,
    emit_startup_report,
)


VALID_ENV = {
    "HOST": "127.0.0.1",
    "PORT": "8081",
    "COMMAND_START": '["/"]',
    "BOT_ADMINS": "10000",
    "SUPERUSERS": '["10000"]',
    "DEEPSEEK_API_KEY": "secret-api-key",
    "ONEBOT_ACCESS_TOKEN": "secret-access-token",
    "DAILY_GREET_GROUPS": "20000",
    "RANDOM_REPLY_CHANCE": "0.01",
    "BACKUP_HOUR": "3",
    "BACKUP_MINUTE": "0",
    "GROUP_CHAT_LOG_RETENTION_DAYS": "30",
    "BACKUP_KEEP_DAYS": "14",
    "BACKUP_KEEP_COUNT": "7",
    "BACKUP_INCLUDE_GROUP_CHAT_LOGS": "true",
    "BACKUP_INCLUDE_IMAGE_LIBRARY": "false",
}


class StartupPreflightTest(unittest.TestCase):
    def _paths(self, root: Path):
        return (
            ("DATA_DIR", root / "data"),
            ("LOG_DIR", root / "logs"),
            ("BACKUP_DIR", root / "backups"),
        )

    def test_first_start_reports_missing_env_without_blocking(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = check_startup_configuration(
                environ={},
                env_file=root / ".env",
                runtime_directories=self._paths(root),
            )

        self.assertFalse(report.has_errors)
        self.assertIn("env.missing", {result.code for result in report.results})
        self.assertIn("ai.disabled", {result.code for result in report.results})

    def test_missing_optional_configuration_only_warns(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            report = check_startup_configuration(
                environ={
                    "HOST": "localhost",
                    "PORT": "8081",
                    "COMMAND_START": '["/"]',
                },
                env_file=env_file,
                runtime_directories=self._paths(root),
            )

        self.assertFalse(report.has_errors)
        warning_codes = {
            result.code for result in report.by_severity(Severity.WARNING)
        }
        self.assertEqual(warning_codes, {"admins.missing", "ai.disabled"})

    def test_invalid_port_is_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            report = check_startup_configuration(
                environ={**VALID_ENV, "PORT": "70000"},
                env_file=env_file,
                runtime_directories=self._paths(root),
            )

        self.assertTrue(report.has_errors)
        self.assertIn("port.invalid", {result.code for result in report.results})

    def test_empty_command_start_warns_but_malformed_value_is_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            warning_report = check_startup_configuration(
                environ={**VALID_ENV, "COMMAND_START": "[]"},
                env_file=env_file,
                runtime_directories=self._paths(root),
            )
            fatal_report = check_startup_configuration(
                environ={**VALID_ENV, "COMMAND_START": "/"},
                env_file=env_file,
                runtime_directories=self._paths(root),
            )

        self.assertFalse(warning_report.has_errors)
        self.assertIn("command_start.empty", {result.code for result in warning_report.results})
        self.assertTrue(fatal_report.has_errors)
        self.assertIn("command_start.invalid", {result.code for result in fatal_report.results})

    def test_superusers_empty_list_is_safe_but_blank_value_is_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            safe_report = check_startup_configuration(
                environ={**VALID_ENV, "BOT_ADMINS": "", "SUPERUSERS": "[]"},
                env_file=env_file,
                runtime_directories=self._paths(root),
            )
            fatal_report = check_startup_configuration(
                environ={**VALID_ENV, "BOT_ADMINS": "", "SUPERUSERS": ""},
                env_file=env_file,
                runtime_directories=self._paths(root),
            )

        self.assertFalse(safe_report.has_errors)
        self.assertIn("admins.missing", {result.code for result in safe_report.results})
        self.assertTrue(fatal_report.has_errors)
        self.assertIn("superusers.invalid", {result.code for result in fatal_report.results})

    def test_unwritable_runtime_directory_is_fatal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()

            def probe(path: Path) -> bool:
                return path.name != "logs"

            report = check_startup_configuration(
                environ=VALID_ENV,
                env_file=env_file,
                runtime_directories=self._paths(root),
                directory_probe=probe,
            )

        self.assertTrue(report.has_errors)
        self.assertIn(
            "directory.log_dir.unwritable",
            {result.code for result in report.results},
        )

    def test_fully_valid_configuration_has_no_warnings_or_errors(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            report = check_startup_configuration(
                environ=VALID_ENV,
                env_file=env_file,
                runtime_directories=self._paths(root),
            )

        self.assertFalse(report.has_errors)
        self.assertEqual(report.by_severity(Severity.WARNING), ())

    def test_python_version_and_retention_values_are_checked(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            report = check_startup_configuration(
                environ={
                    **VALID_ENV,
                    "GROUP_CHAT_LOG_RETENTION_DAYS": "-1",
                    "BACKUP_INCLUDE_GROUP_CHAT_LOGS": "maybe",
                },
                env_file=env_file,
                runtime_directories=self._paths(root),
                python_version=(3, 10, 16),
            )

        self.assertTrue(report.has_errors)
        codes = {result.code for result in report.results}
        self.assertIn("python.unsupported", codes)
        self.assertIn("group_chat_log_retention_days.invalid", codes)
        self.assertIn("backup_include_group_chat_logs.invalid", codes)
        self.assertEqual(
            next(
                result.severity
                for result in report.results
                if result.code == "group_chat_log_retention_days.invalid"
            ),
            Severity.WARNING,
        )

    def test_rendered_output_never_contains_secrets_ids_or_absolute_paths(self):
        secret_key = "".join(("sk", "-sensitive-value"))
        access_token = "".join(("token", "-sensitive-value"))
        admin_id = "123456789"
        group_id = "987654321"
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.touch()
            report = check_startup_configuration(
                environ={
                    **VALID_ENV,
                    "DEEPSEEK_API_KEY": secret_key,
                    "ONEBOT_ACCESS_TOKEN": access_token,
                    "BOT_ADMINS": admin_id,
                    "SUPERUSERS": f'["{admin_id}"]',
                    "DAILY_GREET_GROUPS": group_id,
                },
                env_file=env_file,
                runtime_directories=self._paths(root),
            )
            output = StringIO()
            emit_startup_report(report, output)
            rendered = output.getvalue()

        for sensitive_value in (
            secret_key,
            access_token,
            admin_id,
            group_id,
            str(root.resolve()),
        ):
            self.assertNotIn(sensitive_value, rendered)
        self.assertIn("DEEPSEEK_API_KEY", rendered)
        self.assertIn("BOT_ADMINS", rendered)

    def test_fatal_report_exits_before_bot_initialization(self):
        from mybot import bot

        report = PreflightReport(
            (
                CheckResult(
                    "port.invalid",
                    Severity.ERROR,
                    "PORT",
                    "设置为合法端口。",
                ),
            )
        )
        with (
            patch.object(bot, "load_startup_environment"),
            patch.object(bot, "check_startup_configuration", return_value=report),
            patch.object(bot, "emit_startup_report"),
            patch.object(bot, "initialize_bot") as initialize,
        ):
            with self.assertRaises(SystemExit) as raised:
                bot.bootstrap()

        self.assertEqual(raised.exception.code, PREFLIGHT_EXIT_CODE)
        initialize.assert_not_called()

    def test_warning_report_preserves_no_argument_startup(self):
        from mybot import bot

        report = PreflightReport(
            (
                CheckResult(
                    "ai.disabled",
                    Severity.WARNING,
                    "DEEPSEEK_API_KEY",
                    "需要时再配置。",
                ),
            )
        )
        runtime = Mock()
        with (
            patch.object(bot, "load_startup_environment"),
            patch.object(bot, "check_startup_configuration", return_value=report),
            patch.object(bot, "emit_startup_report"),
            patch.object(bot, "initialize_bot", return_value=runtime),
        ):
            self.assertIs(bot.bootstrap(), runtime)

        self.assertEqual(tuple(inspect.signature(bot.main).parameters), ())


if __name__ == "__main__":
    unittest.main()
