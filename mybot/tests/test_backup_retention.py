from datetime import date, datetime
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common.backup import (
    create_verified_backup,
    verify_backup_archive,
    verify_backup_checksum,
)
from mybot.common.config import (
    MAX_BACKUP_KEEP_COUNT,
    MAX_RETENTION_DAYS,
    RetentionSettings,
    get_retention_settings,
)
from mybot.common.retention import (
    RetentionSafetyError,
    apply_cleanup_plan,
    apply_retention_after_verified_backup,
    plan_backup_cleanup,
    plan_group_chat_log_cleanup,
)


RETENTION_ENV = {
    "GROUP_CHAT_LOG_RETENTION_DAYS",
    "BACKUP_KEEP_DAYS",
    "BACKUP_KEEP_COUNT",
    "BACKUP_INCLUDE_GROUP_CHAT_LOGS",
    "BACKUP_INCLUDE_IMAGE_LIBRARY",
}


def _write(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _backup_pair(root: Path, timestamp: str) -> tuple[Path, Path]:
    backup = _write(root / f"bot_backup_{timestamp}.tar.gz", timestamp)
    checksum = _write(root / f"{backup.name}.sha256", "checksum")
    return backup, checksum


class RetentionConfigTest(unittest.TestCase):
    def _settings(self, values: dict[str, str]) -> RetentionSettings:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in RETENTION_ENV
        }
        environment.update(values)
        with patch.dict(os.environ, environment, clear=True):
            return get_retention_settings()

    def test_defaults_disable_cleanup_and_include_group_logs(self):
        settings = self._settings({})

        self.assertTrue(settings.is_valid)
        self.assertFalse(settings.cleanup_enabled)
        self.assertEqual(settings.group_chat_log_retention_days, 0)
        self.assertEqual(settings.backup_keep_days, 0)
        self.assertEqual(settings.backup_keep_count, 0)
        self.assertTrue(settings.backup_include_group_chat_logs)
        self.assertFalse(settings.backup_include_image_library)

    def test_valid_retention_values_are_loaded(self):
        settings = self._settings(
            {
                "GROUP_CHAT_LOG_RETENTION_DAYS": "30",
                "BACKUP_KEEP_DAYS": "14",
                "BACKUP_KEEP_COUNT": "7",
                "BACKUP_INCLUDE_GROUP_CHAT_LOGS": "false",
                "BACKUP_INCLUDE_IMAGE_LIBRARY": "true",
            }
        )

        self.assertTrue(settings.is_valid)
        self.assertTrue(settings.cleanup_enabled)
        self.assertEqual(settings.group_chat_log_retention_days, 30)
        self.assertEqual(settings.backup_keep_days, 14)
        self.assertEqual(settings.backup_keep_count, 7)
        self.assertFalse(settings.backup_include_group_chat_logs)
        self.assertTrue(settings.backup_include_image_library)

    def test_invalid_numbers_and_boolean_disable_cleanup_safely(self):
        settings = self._settings(
            {
                "GROUP_CHAT_LOG_RETENTION_DAYS": "-1",
                "BACKUP_KEEP_DAYS": "not-a-number",
                "BACKUP_KEEP_COUNT": str(MAX_BACKUP_KEEP_COUNT + 1),
                "BACKUP_INCLUDE_GROUP_CHAT_LOGS": "maybe",
            }
        )

        self.assertFalse(settings.is_valid)
        self.assertFalse(settings.cleanup_enabled)
        self.assertEqual(settings.group_chat_log_retention_days, 0)
        self.assertEqual(settings.backup_keep_days, 0)
        self.assertEqual(settings.backup_keep_count, 0)
        self.assertTrue(settings.backup_include_group_chat_logs)
        self.assertEqual(len(settings.errors), 4)

    def test_oversized_day_value_is_rejected(self):
        settings = self._settings(
            {"GROUP_CHAT_LOG_RETENTION_DAYS": str(MAX_RETENTION_DAYS + 1)}
        )

        self.assertFalse(settings.is_valid)
        self.assertEqual(settings.group_chat_log_retention_days, 0)


class GroupChatLogRetentionTest(unittest.TestCase):
    def test_dry_run_counts_only_expired_well_formed_logs(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "group_chat_logs"
            expired = _write(root / "123456" / "2026" / "07" / "10.yaml", "old")
            boundary = _write(root / "123456" / "2026" / "07" / "11.yaml", "edge")
            today_file = _write(root / "123456" / "2026" / "07" / "13.yaml", "today")
            unknown = _write(root / "123456" / "2026" / "07" / "notes.txt", "keep")
            invalid_group = _write(root / "group-name" / "2025" / "01" / "01.yaml", "keep")

            plan = plan_group_chat_log_cleanup(
                root,
                retention_days=2,
                today=date(2026, 7, 13),
            )

            self.assertTrue(plan.is_valid)
            self.assertEqual(plan.candidate_count, 1)
            self.assertEqual(plan.size_bytes, len("old"))
            self.assertEqual(plan.date_range, (date(2026, 7, 10), date(2026, 7, 10)))
            for path in (expired, boundary, today_file, unknown, invalid_group):
                self.assertTrue(path.exists(), "dry-run must not modify files")

    def test_apply_deletes_candidates_and_only_empty_known_directories(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "group_chat_logs"
            expired = _write(root / "123456" / "2025" / "01" / "01.yaml")
            kept = _write(root / "654321" / "2026" / "07" / "13.yaml")

            plan = plan_group_chat_log_cleanup(
                root,
                retention_days=30,
                today=date(2026, 7, 13),
            )
            result = apply_cleanup_plan(plan)

            self.assertEqual(result.deleted_count, 1)
            self.assertFalse(expired.exists())
            self.assertFalse((root / "123456").exists())
            self.assertTrue(kept.exists())

            second_plan = plan_group_chat_log_cleanup(
                root,
                retention_days=30,
                today=date(2026, 7, 13),
            )
            self.assertEqual(second_plan.candidate_count, 0)

    def test_zero_retention_does_not_touch_files(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "group_chat_logs"
            expired = _write(root / "123456" / "2020" / "01" / "01.yaml")

            plan = plan_group_chat_log_cleanup(root, retention_days=0)
            result = apply_cleanup_plan(plan)

            self.assertEqual(result.deleted_count, 0)
            self.assertTrue(expired.exists())

    def test_symlink_is_ignored_and_outside_file_is_preserved(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "group_chat_logs"
            month = root / "123456" / "2020" / "01"
            month.mkdir(parents=True)
            outside = _write(base / "outside.yaml", "outside")
            link = month / "01.yaml"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            plan = plan_group_chat_log_cleanup(
                root,
                retention_days=1,
                today=date(2026, 7, 13),
            )
            result = apply_cleanup_plan(plan)

            self.assertEqual(result.deleted_count, 0)
            self.assertTrue(link.exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside")


class BackupRetentionTest(unittest.TestCase):
    def test_days_and_count_use_conservative_intersection(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "backups"
            newest, _ = _backup_pair(root, "20260713_110000")
            within_count, _ = _backup_pair(root, "20260712_110000")
            expired, expired_checksum = _backup_pair(root, "20260710_110000")
            unknown = _write(root / "manual_backup.tar.gz")
            temporary = _write(root / ".bot_backup_diagnostic.tmp")

            plan = plan_backup_cleanup(
                root,
                keep_days=2,
                keep_count=2,
                now=datetime(2026, 7, 13, 12),
            )

            self.assertEqual(plan.candidate_count, 1)
            self.assertTrue(expired.exists(), "dry-run must not remove the archive")
            result = apply_cleanup_plan(plan)
            self.assertEqual(result.deleted_count, 1)
            self.assertFalse(expired.exists())
            self.assertFalse(expired_checksum.exists())
            for path in (newest, within_count, unknown, temporary):
                self.assertTrue(path.exists())

    def test_count_only_keeps_latest_archives(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "backups"
            paths = [
                _backup_pair(root, timestamp)[0]
                for timestamp in (
                    "20260713_110000",
                    "20260712_110000",
                    "20260711_110000",
                    "20260710_110000",
                )
            ]

            plan = plan_backup_cleanup(root, keep_days=0, keep_count=2)

            self.assertEqual(plan.candidate_count, 2)
            self.assertEqual(
                {candidate.path.resolve() for candidate in plan.candidates},
                {path.resolve() for path in paths[2:]},
            )


class VerifiedBackupTest(unittest.TestCase):
    def _sources(self, bot_root: Path) -> tuple[tuple[Path, str], ...]:
        return (
            (bot_root / "data", "data"),
            (bot_root / "plugins", "plugins"),
            (bot_root / ".env.example", ".env.example"),
        )

    def test_verified_backup_excludes_optional_large_runtime_directories(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bot_root = root / "mybot"
            backup_root = root / "backups"
            for filename in (
                "points.json",
                "taibai_tavern.json",
                "paid_rounds.json",
                "admin_permissions.json",
                "feature_flags.json",
            ):
                _write(bot_root / "data" / filename, "{}")
            _write(
                bot_root / "data" / "group_chat_logs" / "123456" / "2026" / "07" / "13.yaml",
                "message",
            )
            _write(
                bot_root / "data" / "image_library" / "123456" / "images" / "sample.png",
                "image",
            )
            _write(bot_root / "plugins" / "example.py", "VALUE = 1")
            _write(bot_root / ".env.example", "KEY=")
            _write(bot_root / ".env", "SECRET=do-not-back-up")

            result = create_verified_backup(
                backup_dir=backup_root,
                sources=self._sources(bot_root),
                include_group_chat_logs=False,
                group_chat_log_root=bot_root / "data" / "group_chat_logs",
                image_library_root=bot_root / "data" / "image_library",
                now=datetime(2026, 7, 13, 12),
            )

            self.assertTrue(result.path.exists())
            self.assertTrue(result.checksum_path.exists())
            self.assertTrue(verify_backup_checksum(result.path, result.checksum_path))
            self.assertEqual(verify_backup_archive(result.path), result.member_count)
            self.assertFalse(any(backup_root.glob("*.tmp")))
            with tarfile.open(result.path, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}
            for filename in (
                "points.json",
                "taibai_tavern.json",
                "paid_rounds.json",
                "admin_permissions.json",
                "feature_flags.json",
            ):
                self.assertIn(f"data/{filename}", names)
            self.assertFalse(any(name.startswith("data/group_chat_logs") for name in names))
            self.assertFalse(any(name.startswith("data/image_library") for name in names))
            self.assertNotIn(".env", names)

    def test_image_library_can_be_included_explicitly(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bot_root = root / "mybot"
            backup_root = root / "backups"
            image = _write(
                bot_root / "data" / "image_library" / "123456" / "images" / "sample.png",
                "image",
            )
            _write(bot_root / "plugins" / "example.py", "VALUE = 1")
            _write(bot_root / ".env.example", "KEY=")

            result = create_verified_backup(
                backup_dir=backup_root,
                sources=self._sources(bot_root),
                include_image_library=True,
                image_library_root=bot_root / "data" / "image_library",
                now=datetime(2026, 7, 13, 13),
            )

            with tarfile.open(result.path, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}
            self.assertIn(
                "data/image_library/123456/images/sample.png",
                names,
            )
            self.assertTrue(image.exists())

    def test_corrupted_new_backup_prevents_all_cleanup(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bot_root = root / "mybot"
            backup_root = root / "backups"
            group_root = bot_root / "data" / "group_chat_logs"
            _write(bot_root / "data" / "points.json", "{}")
            _write(bot_root / "plugins" / "example.py", "VALUE = 1")
            _write(bot_root / ".env.example", "KEY=")
            old_backup, _ = _backup_pair(backup_root, "20200101_000000")
            old_group_log = _write(group_root / "123456" / "2020" / "01" / "01.yaml")
            result = create_verified_backup(
                backup_dir=backup_root,
                sources=self._sources(bot_root),
                group_chat_log_root=group_root,
                now=datetime(2026, 7, 13, 12),
            )
            result.path.write_bytes(b"corrupted")
            settings = RetentionSettings(
                group_chat_log_retention_days=1,
                backup_keep_count=1,
            )

            with self.assertRaises(Exception):
                apply_retention_after_verified_backup(
                    settings,
                    result,
                    group_log_root=group_root,
                    backup_root=backup_root,
                    now=datetime(2026, 7, 13, 12),
                )

            self.assertTrue(old_backup.exists())
            self.assertTrue(old_group_log.exists())

    def test_invalid_config_refuses_cleanup(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bot_root = root / "mybot"
            backup_root = root / "backups"
            _write(bot_root / "data" / "points.json", "{}")
            _write(bot_root / "plugins" / "example.py", "VALUE = 1")
            _write(bot_root / ".env.example", "KEY=")
            old_backup, _ = _backup_pair(backup_root, "20200101_000000")
            result = create_verified_backup(
                backup_dir=backup_root,
                sources=self._sources(bot_root),
                group_chat_log_root=bot_root / "data" / "group_chat_logs",
                now=datetime(2026, 7, 13, 12),
            )
            settings = RetentionSettings(backup_keep_count=1, errors=("invalid",))

            with self.assertRaises(RetentionSafetyError):
                apply_retention_after_verified_backup(
                    settings,
                    result,
                    group_log_root=bot_root / "data" / "group_chat_logs",
                    backup_root=backup_root,
                    now=datetime(2026, 7, 13, 12),
                )

            self.assertTrue(old_backup.exists())


if __name__ == "__main__":
    unittest.main()
