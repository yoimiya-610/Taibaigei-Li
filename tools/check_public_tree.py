"""Fail when the public Git tree contains private or operational material."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_DIRECTORY_NAMES = {
    ".agents",
    ".codex",
    ".codex_worktrees",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "backups",
    "env",
    "lagrange",
    "logs",
    "mybot.egg-info",
    "napcat",
    "venv",
}
FORBIDDEN_RELATIVE_PREFIXES = (
    "mybot/data/",
    "mybot/logs/",
)
FORBIDDEN_EXACT_PATHS = {
    ".codex_pr_body.md",
    ".codex_release_notes_v0.2.2.md",
    "napcat.sh",
    ".github/public-upstream-state.json",
    ".github/public-upstream-conflict.json",
    ".github/workflows/sync-public-upstream.yml",
    "tools/export_public_release.py",
    "tools/public_upstream_manifest.json",
    "tools/sync_public_upstream.py",
    "tools/stage_public_upstream_changes.py",
}
FORBIDDEN_SUFFIXES = {
    ".bak",
    ".db",
    ".db-shm",
    ".db-wal",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_COMPOUND_SUFFIXES = (".tar.bz2", ".tar.gz", ".tar.xz")
FORBIDDEN_CONFIG_NAMES = {
    "onebot11.json",
    "webui.json",
}
TEXT_SUFFIXES = {
    "",
    ".example",
    ".gitignore",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
CONTENT_SCAN_EXEMPTIONS = {
    "mybot/tests/test_public_tree.py",
    "tools/check_public_tree.py",
}
EMPTY_PUBLIC_ENV_KEYS = {
    "BOT_ADMINS",
    "DAILY_GREET_GROUPS",
    "DEEPSEEK_API_KEY",
    "ONEBOT_ACCESS_TOKEN",
}
REQUIRED_PATHS = {
    ".github/workflows/ci.yml",
    ".gitignore",
    "CONTRIBUTING.md",
    "LICENSE",
    "PUBLIC_RELEASE_MANIFEST.md",
    "README.md",
    "docs/configuration.md",
    "docs/deployment.md",
    "docs/upgrading.md",
    "mybot/.env.example",
    "tools/check_public_tree.py",
}

CONTENT_PATTERNS = (
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    ),
    (
        "provider secret",
        re.compile(r"\b(?:sk|gh[pousr])-[A-Za-z0-9_-]{16,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "credential assignment",
        re.compile(
            r"""(?m)^[ \t]*(?:[A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|PASSWORD|SECRET)|TOKEN)[ \t]*=[ \t]*[^\s#][^\r\n#]{7,}$"""
        ),
    ),
    (
        "literal credential",
        re.compile(
            r"""(?im)^[ \t]*[A-Za-z_][A-Za-z0-9_]*(?:api_key|access_token|password|secret|token)[A-Za-z0-9_]*[ \t]*=[ \t]*["'][^"'{}\s]{8,}["'][ \t]*(?:#.*)?$"""
        ),
    ),
    (
        "private administrator default",
        re.compile(r"(?m)^[ \t]*(?:BOT_ADMINS|DAILY_GREET_GROUPS|SUPERUSERS)[ \t]*=[ \t]*[^\s#][^\r\n#]*$"),
    ),
    (
        "private list default",
        re.compile(
            r"""get_env_int_list\(\s*["'](?:BOT_ADMINS|DAILY_GREET_GROUPS)["']\s*,""",
            re.IGNORECASE,
        ),
    ),
    (
        "private repository",
        re.compile(r"github\.com/yoimiya-610/qqbot(?:\.git)?\b", re.IGNORECASE),
    ),
    (
        "private infrastructure label",
        re.compile(r"\b(?:aliyun|Litaibaigei|Topdesk)\b", re.IGNORECASE),
    ),
    (
        "absolute Windows path",
        re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    ),
    (
        "private absolute home path",
        re.compile(r"(?<![A-Za-z0-9])/(?:root|home/[^/\s]+|Users/[^/\s]+)/"),
    ),
    (
        "legacy deployment path",
        re.compile(r"~[\\/]qqbot\b", re.IGNORECASE),
    ),
)
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
ALLOWED_IPV4_LITERALS = {"0.0.0.0", "127.0.0.1"}
# Deliberate SSRF rejection fixture, never a deployment address. All other
# content checks, including credentials and paths, still apply to this file.
SYNTHETIC_IPV4_FIXTURES = {"mybot/tests/test_image_library.py": {"10.0.0.1"}}


class Finding:
    def __init__(self, code: str, path: Path, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code}: {self.path.as_posix()}: {self.detail}"


def discover_repository_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    paths = (
        Path(os.fsdecode(item))
        for item in result.stdout.split(b"\0")
        if item
    )
    return sorted(path for path in paths if (root / path).is_file())


def _path_finding(relative_path: Path) -> Finding | None:
    posix = relative_path.as_posix()
    lower = posix.lower()
    parts = {part.lower() for part in relative_path.parts}
    name = relative_path.name.lower()

    if posix in FORBIDDEN_EXACT_PATHS:
        return Finding("forbidden-path", relative_path, "file must not be published")
    if any(part in FORBIDDEN_DIRECTORY_NAMES for part in parts):
        return Finding("forbidden-directory", relative_path, "runtime or local-only directory")
    if any(lower.startswith(prefix) for prefix in FORBIDDEN_RELATIVE_PREFIXES):
        return Finding("runtime-data", relative_path, "runtime state must stay outside Git")
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return Finding("environment-file", relative_path, "only .env.example may be published")
    if name in FORBIDDEN_CONFIG_NAMES or (
        name.startswith("onebot11_") and relative_path.suffix.lower() == ".json"
    ):
        return Finding("adapter-config", relative_path, "local OneBot configuration")
    if lower.endswith(FORBIDDEN_COMPOUND_SUFFIXES) or relative_path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return Finding("forbidden-file-type", relative_path, "runtime, secret, or backup file type")
    return None


def _content_findings(relative_path: Path, content: str) -> list[Finding]:
    if relative_path.as_posix() in CONTENT_SCAN_EXEMPTIONS:
        return []

    findings: list[Finding] = []
    for label, pattern in CONTENT_PATTERNS:
        if pattern.search(content):
            findings.append(Finding("private-content", relative_path, label))

    for match in IPV4_PATTERN.finditer(content):
        value = match.group(0)
        octets = value.split(".")
        if (
            octets[0] != "0"
            and all(int(octet) <= 255 for octet in octets)
            and value not in ALLOWED_IPV4_LITERALS
            and value not in SYNTHETIC_IPV4_FIXTURES.get(relative_path.as_posix(), set())
        ):
            findings.append(Finding("private-host", relative_path, f"non-loopback IPv4 literal {value}"))
    return findings


def scan_paths(root: Path, relative_paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in sorted(set(relative_paths)):
        path_finding = _path_finding(relative_path)
        if path_finding is not None:
            findings.append(path_finding)

        path = root / relative_path
        if not path.is_file():
            continue
        if relative_path.name not in {".gitignore", "LICENSE"} and path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("text-encoding", relative_path, "expected UTF-8 text"))
            continue
        findings.extend(_content_findings(relative_path, content))
    return findings


def _read_version(path: Path, pattern: str) -> str | None:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def repository_invariants(root: Path, relative_paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    published = {path.as_posix() for path in relative_paths}

    for required in sorted(REQUIRED_PATHS - published):
        findings.append(Finding("missing-required-file", Path(required), "public baseline requirement"))

    env_path = root / "mybot/.env.example"
    if env_path.is_file():
        values: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        for key in sorted(EMPTY_PUBLIC_ENV_KEYS):
            if values.get(key):
                findings.append(Finding("private-default", Path("mybot/.env.example"), f"{key} must be empty"))

    blacklist_path = root / "mybot/plugins/blacklist.py"
    if blacklist_path.is_file():
        blacklist_text = blacklist_path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^BLACKLIST_WORDS\s*=\s*\[\s*\]\s*$", blacklist_text):
            findings.append(Finding("private-default", Path("mybot/plugins/blacklist.py"), "BLACKLIST_WORDS must be empty"))

    version_path = root / "mybot/common/version.py"
    project_path = root / "mybot/pyproject.toml"
    lock_path = root / "mybot/uv.lock"
    if version_path.is_file() and project_path.is_file() and lock_path.is_file():
        versions = {
            "__version__": _read_version(version_path, r'^__version__ = "([^"]+)"$'),
            "pyproject": _read_version(project_path, r'^version = "([^"]+)"$'),
            "uv.lock": _read_version(lock_path, r'\[\[package\]\]\s+name = "mybot"\s+version = "([^"]+)"'),
        }
        if len(set(versions.values())) != 1 or None in versions.values():
            findings.append(Finding("version-mismatch", Path("mybot"), repr(versions)))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    paths = discover_repository_paths(root)
    findings = scan_paths(root, paths)
    findings.extend(repository_invariants(root, paths))

    if findings:
        print("Public tree check failed:")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    print(f"Public tree check passed ({len(paths)} files scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
