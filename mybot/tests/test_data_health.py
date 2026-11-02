from pathlib import Path
import json
import tempfile
import unittest

import mybot.bot  # noqa: F401
from mybot.common.data_health import (
    DATA_MANIFEST_SCHEMA_VERSION,
    EXPECTED_SCHEDULED_JOBS,
    DiagnosticSeverity,
    inspect_plugins,
    inspect_storage,
    inspect_tasks,
    iter_data_file_manifest,
)
from mybot.common.plugin_metadata import iter_plugin_metadata


class _Job:
    def __init__(self, job_id: str, next_run_time=object()):
        self.id = job_id
        self.next_run_time = next_run_time


class _Scheduler:
    running = True

    def __init__(self, jobs):
        self._jobs = jobs

    def get_jobs(self):
        return list(self._jobs)


def _healthy_scheduler() -> _Scheduler:
    return _Scheduler([_Job(job_id) for job_id in EXPECTED_SCHEDULED_JOBS])


class DataHealthTest(unittest.TestCase):
    def test_manifest_is_versioned_and_matches_plugin_metadata(self):
        specs = iter_data_file_manifest()
        manifest_paths = {spec.path for spec in specs}
        metadata_paths = {
            path
            for metadata in iter_plugin_metadata()
            for path in metadata.data_files
        }
        self.assertEqual(DATA_MANIFEST_SCHEMA_VERSION, 1)
        self.assertEqual(len(specs), len(manifest_paths))
        self.assertEqual(manifest_paths, metadata_paths)
        self.assertTrue(all(spec.schema_version >= 1 for spec in specs))
        self.assertEqual(inspect_plugins().issues, ())

    def test_corrupt_json_is_reported_without_modifying_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data" / "points.json"
            path.parent.mkdir(parents=True)
            original = b'{"broken": '
            path.write_bytes(original)

            report = inspect_storage(root)

            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(
                any(item.code == "invalid_json" and item.path == "data/points.json" for item in report.issues)
            )
            self.assertEqual(report.existing_entries, 1)
            self.assertEqual(report.missing_entries, report.manifest_entries - 1)

    def test_future_schema_and_missing_required_collection_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data" / "paid_rounds.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"version": 2, "rounds": []}), encoding="utf-8")

            report = inspect_storage(root)
            codes = {item.code for item in report.issues}
            self.assertIn("future_schema_version", codes)
            self.assertIn("invalid_collection", codes)
            self.assertTrue(all(item.severity is DiagnosticSeverity.ERROR for item in report.issues))

    def test_native_group_log_shape_is_accepted_as_utf8_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data" / "group_chat_logs" / "20001" / "2026" / "07" / "16.yaml"
            path.parent.mkdir(parents=True)
            path.write_text('-\n  time: "12:00:00"\n  user_id: "10001"\n', encoding="utf-8")

            report = inspect_storage(root)

            self.assertNotIn("unexpected_yaml_shape", {item.code for item in report.issues})
            self.assertEqual(report.checked_files, 1)

    def test_task_health_reports_unfinished_rounds_and_abnormal_queue_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            (data_root / "paid_rounds.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rounds": {
                            "r1": {"state": "active", "deadline_at": 10},
                            "r2": {"state": "settled"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (data_root / "group_card_queue.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "jobs": {
                            "1:2": {
                                "group_id": "1",
                                "user_id": "2",
                                "due_at": "2026-07-16T12:00:00",
                                "attempts": 8,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = inspect_tasks(_healthy_scheduler(), data_root=data_root, now_timestamp=20)

            self.assertEqual(report.unfinished_paid_rounds, 1)
            self.assertEqual(report.due_paid_rounds, 1)
            self.assertEqual(report.queued_card_jobs, 1)
            self.assertEqual(report.abnormal_card_jobs, 1)
            self.assertEqual(report.missing_jobs, ())
            self.assertTrue(report.recovery_hooks_installed)
            self.assertIn("unfinished_paid_rounds", {item.code for item in report.issues})
            self.assertIn("abnormal_card_jobs", {item.code for item in report.issues})


if __name__ == "__main__":
    unittest.main()
