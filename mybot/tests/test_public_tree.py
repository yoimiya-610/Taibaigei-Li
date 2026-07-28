import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = PROJECT_ROOT / "tools" / "check_public_tree.py"

spec = importlib.util.spec_from_file_location("check_public_tree", CHECK_SCRIPT)
check_public_tree = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_public_tree)


class PublicTreeCheckTest(unittest.TestCase):
    def _scan(self, relative_path: str, content: str = ""):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return check_public_tree.scan_paths(root, [Path(relative_path)])

    def test_safe_public_template_passes(self):
        findings = self._scan(
            "mybot/.env.example",
            "HOST=127.0.0.1\nBOT_ADMINS=\nDEEPSEEK_API_KEY=\n",
        )
        self.assertEqual(findings, [])

    def test_runtime_data_path_is_rejected(self):
        findings = self._scan("mybot/data/points.json", "{}")
        self.assertTrue(any(item.code == "runtime-data" for item in findings))

    def test_secret_assignment_is_rejected(self):
        findings = self._scan("mybot/.env.example", "DEEPSEEK_API_KEY=sk-example-secret-value\n")
        self.assertTrue(any(item.code == "private-content" for item in findings))

    def test_private_admin_default_is_rejected(self):
        findings = self._scan("mybot/.env.example", "BOT_ADMINS=123456\n")
        self.assertTrue(any(item.code == "private-content" for item in findings))

    def test_private_paths_and_remotes_are_rejected(self):
        findings = self._scan(
            "README.md",
            "clone from github.com/yoimiya-610/qqbot.git into /root/service/\n",
        )
        self.assertGreaterEqual(len(findings), 2)

    def test_non_loopback_ip_is_rejected(self):
        findings = self._scan("config.md", "HOST=192.0.2.10\n")
        self.assertTrue(any(item.code == "private-host" for item in findings))

    def test_redistributed_napcat_installer_is_rejected(self):
        findings = self._scan("napcat.sh", "#!/usr/bin/env bash\n")
        self.assertTrue(any(item.code == "forbidden-path" for item in findings))


if __name__ == "__main__":
    unittest.main()
