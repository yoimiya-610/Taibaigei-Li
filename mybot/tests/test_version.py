from pathlib import Path
import re
import unittest

from mybot.common.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_project_version() -> str:
    pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
    if not match:
        raise AssertionError("pyproject.toml missing project version")
    return match.group(1)


def _read_lock_version() -> str:
    lock_text = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    match = re.search(r'\[\[package\]\]\s+name = "mybot"\s+version = "([^"]+)"', lock_text)
    if not match:
        raise AssertionError("uv.lock missing mybot package version")
    return match.group(1)


class VersionTest(unittest.TestCase):
    def test_version_metadata_is_in_sync(self):
        self.assertEqual(__version__, "0.1.5")
        self.assertEqual(_read_project_version(), __version__)
        self.assertEqual(_read_lock_version(), __version__)



if __name__ == "__main__":
    unittest.main()
