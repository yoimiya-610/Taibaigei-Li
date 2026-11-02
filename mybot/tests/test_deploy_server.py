import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import textwrap
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "tools" / "deploy_server.sh"


@unittest.skipIf(os.name == "nt", "deployment script integration tests require POSIX")
class DeployServerScriptTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.tools_dir = self.root / "tools"
        self.bot_dir = self.root / "mybot"
        self.bin_dir = self.root / "bin"
        self.tools_dir.mkdir()
        self.bot_dir.mkdir()
        self.bin_dir.mkdir()
        deploy_copy = self.tools_dir / "deploy_server.sh"
        with deploy_copy.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(DEPLOY_SCRIPT.read_text(encoding="utf-8"))
        shutil.copymode(DEPLOY_SCRIPT, deploy_copy)
        (self.bot_dir / "bot.py").write_text("# deployment fixture\n", encoding="utf-8")
        self.state_file = self.root / "service.state"
        self.call_log = self.root / "calls.log"
        self._install_fake_commands()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_command(self, name: str, source: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def _install_fake_commands(self) -> None:
        self._write_command(
            "git",
            r"""
            #!/usr/bin/env bash
            set -eu
            printf 'git:%s\n' "$*" >> "$CALL_LOG"
            if [[ "${1:-}" == "-C" ]]; then
                shift 2
            fi
            case "${1:-}" in
                diff|fetch|merge-base|merge|ls-tree)
                    exit 0
                    ;;
                rev-parse)
                    case "${2:-}" in
                        --is-inside-work-tree) printf 'true\n' ;;
                        HEAD) printf '%s\n' "$CURRENT_COMMIT" ;;
                        FETCH_HEAD) printf '%s\n' "$INCOMING_COMMIT" ;;
                        *) exit 2 ;;
                    esac
                    ;;
                *)
                    exit 2
                    ;;
            esac
            """,
        )
        self._write_command(
            "systemctl",
            r"""
            #!/usr/bin/env bash
            set -eu
            printf 'systemctl:%s\n' "$*" >> "$CALL_LOG"
            case "${1:-}" in
                is-active)
                    [[ "$(cat "$SYSTEMCTL_STATE_FILE")" == "active" ]]
                    ;;
                is-failed)
                    [[ "$(cat "$SYSTEMCTL_STATE_FILE")" == "failed" ]]
                    ;;
                show)
                    case "$*" in
                        *LoadState*) printf 'loaded\n' ;;
                        *MainPID*)
                            if [[ "$(cat "$SYSTEMCTL_STATE_FILE")" == "active" ]]; then
                                printf '%s\n' "$TEST_MAIN_PID"
                            else
                                printf '0\n'
                            fi
                            ;;
                        *) exit 2 ;;
                    esac
                    ;;
                stop)
                    printf 'inactive\n' > "$SYSTEMCTL_STATE_FILE"
                    ;;
                start)
                    if [[ "${START_BEHAVIOR:-success}" == "fail" ]]; then
                        printf 'failed\n' > "$SYSTEMCTL_STATE_FILE"
                        exit 1
                    fi
                    printf 'active\n' > "$SYSTEMCTL_STATE_FILE"
                    ;;
                status)
                    printf 'fake service status: %s\n' "$(cat "$SYSTEMCTL_STATE_FILE")"
                    ;;
                *)
                    exit 2
                    ;;
            esac
            """,
        )
        self._write_command(
            "uv",
            r"""
            #!/usr/bin/env bash
            set -eu
            printf 'uv:%s\n' "$*" >> "$CALL_LOG"
            [[ "${UV_FAIL:-0}" != "1" ]]
            """,
        )
        self._write_command(
            "journalctl",
            r"""
            #!/usr/bin/env bash
            set -eu
            printf 'journalctl:%s\n' "$*" >> "$CALL_LOG"
            printf 'fake journal\n'
            """,
        )

    def _run_deploy(
        self,
        *,
        current: str,
        incoming: str,
        state: str,
        uv_fail: bool = False,
        start_behavior: str = "success",
    ) -> subprocess.CompletedProcess[str]:
        self.state_file.write_text(f"{state}\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                "CALL_LOG": str(self.call_log),
                "SYSTEMCTL_STATE_FILE": str(self.state_file),
                "CURRENT_COMMIT": current,
                "INCOMING_COMMIT": incoming,
                "TEST_MAIN_PID": str(os.getpid()),
                "BOT_START_WAIT": "0",
                "UV_FAIL": "1" if uv_fail else "0",
                "START_BEHAVIOR": start_behavior,
            }
        )
        return subprocess.run(
            ["bash", str(self.tools_dir / "deploy_server.sh")],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def _calls(self) -> list[str]:
        return self.call_log.read_text(encoding="utf-8").splitlines()

    def test_latest_code_recovers_an_inactive_service(self):
        result = self._run_deploy(current="same", incoming="same", state="inactive")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("service recovery complete", result.stdout)
        self.assertEqual(self.state_file.read_text(encoding="utf-8").strip(), "active")
        calls = self._calls()
        self.assertTrue(any(call.startswith("uv:sync --project") for call in calls))
        self.assertEqual(sum(call.startswith("systemctl:start ") for call in calls), 1)
        self.assertFalse(any("screen" in call.lower() for call in calls))

    def test_dependency_failure_restarts_the_previously_stopped_service(self):
        result = self._run_deploy(
            current="old",
            incoming="new",
            state="active",
            uv_fail=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic service recovery succeeded", result.stdout)
        self.assertEqual(self.state_file.read_text(encoding="utf-8").strip(), "active")
        calls = self._calls()
        self.assertEqual(sum(call.startswith("systemctl:stop ") for call in calls), 1)
        self.assertEqual(sum(call.startswith("systemctl:start ") for call in calls), 1)

    def test_start_failure_reports_diagnostics_without_a_second_start(self):
        result = self._run_deploy(
            current="old",
            incoming="new",
            state="active",
            start_behavior="fail",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("service startup failed; no second instance was started", result.stdout)
        self.assertIn("is in failed state", result.stderr)
        calls = self._calls()
        self.assertEqual(sum(call.startswith("systemctl:start ") for call in calls), 1)
        self.assertTrue(any(call.startswith("systemctl:status ") for call in calls))
        self.assertTrue(any(call.startswith("journalctl:") for call in calls))


if __name__ == "__main__":
    unittest.main()
