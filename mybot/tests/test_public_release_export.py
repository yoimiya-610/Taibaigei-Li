import ast
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = PROJECT_ROOT / "tools" / "export_public_release.py"

spec = importlib.util.spec_from_file_location("export_public_release", EXPORT_SCRIPT)
export_public_release = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(export_public_release)


class PublicReleaseExportTest(unittest.TestCase):
    def _write_config(self, destination: Path, text: str) -> Path:
        config_path = destination / "mybot" / "common" / "config.py"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
        return config_path

    def test_sanitize_release_config_allows_already_safe_daily_groups(self):
        with TemporaryDirectory() as tmp_dir:
            destination = Path(tmp_dir)
            config_path = self._write_config(
                destination,
                'def get_daily_greet_groups():\n    return get_env_int_list("DAILY_GREET_GROUPS")\n',
            )

            export_public_release._sanitize_release_config(destination)

            self.assertIn('get_env_int_list("DAILY_GREET_GROUPS")', config_path.read_text(encoding="utf-8"))
            self.assertTrue((destination / "mybot" / ".env.example").exists())
            self.assertTrue((destination / "PUBLIC_RELEASE_MANIFEST.md").exists())

    def test_sanitize_release_config_removes_legacy_daily_group_default(self):
        with TemporaryDirectory() as tmp_dir:
            destination = Path(tmp_dir)
            legacy_default = "[" + "123456" + "]"
            config_path = self._write_config(
                destination,
                'def get_daily_greet_groups():\n'
                f'    return get_env_int_list("DAILY_GREET_GROUPS", {legacy_default})\n',
            )

            export_public_release._sanitize_release_config(destination)

            self.assertIn('return get_env_int_list("DAILY_GREET_GROUPS")', config_path.read_text(encoding="utf-8"))

    def test_codex_temp_files_are_excluded(self):
        self.assertTrue(
            export_public_release._should_skip(
                Path(".codex_pr_body.md"),
                Path(".codex_pr_body.md"),
                exclude_disabled_plugins=False,
            )
        )

    def test_export_sanitizes_blacklist_words(self):
        with TemporaryDirectory() as tmp_dir:
            destination = Path(tmp_dir) / "release"
            with redirect_stdout(StringIO()):
                export_public_release.export_release(destination, overwrite=False, exclude_disabled_plugins=False)
            blacklist_path = destination / "mybot/plugins/blacklist.py"
            tree = ast.parse(blacklist_path.read_text(encoding="utf-8"))

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "BLACKLIST_WORDS" for target in node.targets):
                self.assertIsInstance(node.value, ast.List)
                self.assertEqual(node.value.elts, [])
                break
        else:
            self.fail("BLACKLIST_WORDS assignment not found in public release")


if __name__ == "__main__":
    unittest.main()
