"""Export a publishable copy of the bot without operational or user data.

The source tree is never modified. The resulting directory has no Git history and
can be initialized as a separate public repository.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = PROJECT_ROOT.parent / "release version"

EXCLUDED_DIRECTORY_NAMES = {
    ".agents",
    ".codex",
    ".codex_worktrees",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "env",
    "venv",
}
EXCLUDED_RELATIVE_DIRECTORIES = {
    Path("backups"),
    Path("mybot/data"),
    Path("mybot/logs"),
    Path("tmp_export_checks"),
}
EXCLUDED_FILES = {
    Path("mybot/！"),
}
EXCLUDED_SUFFIXES = {".bak", ".db", ".pyo", ".pyc", ".sqlite", ".sqlite3"}
EXCLUDED_COMPOUND_SUFFIXES = {".tar.gz", ".tar.xz", ".tar.bz2"}

PUBLIC_ENV_TEMPLATE = """# Copy this file to .env and fill in only values for your own deployment.
DEEPSEEK_API_KEY=
HOST=127.0.0.1
PORT=8081
COMMAND_START=[\"/\"]
BOT_ADMINS=
DAILY_GREET_GROUPS=
RANDOM_REPLY_CHANCE=0.01
BACKUP_HOUR=3
BACKUP_MINUTE=0
"""

PUBLIC_GITIGNORE = """# Local environment and Python caches
.env
.venv/
venv/
env/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Runtime data: may contain QQ IDs, message excerpts, rankings and credentials
mybot/data/
mybot/logs/
backups/
*.log
*.db
*.db-shm
*.db-wal
*.sqlite
*.sqlite3
*.tmp
*.bak

# Local bot adapters and their configuration
napcat/
lagrange/
"""

MANIFEST = """# Public Release Export

This directory is a clean source export. It intentionally contains no `.git`
directory or commit history, so it can be initialized and linked to a new public
remote repository.

The export excludes local environment files, virtual environments, runtime data,
message/points records, logs, backups, caches, database files and temporary files.
The legacy game plugins are included because the bot loads them at runtime and an
administrator can enable them through the feature switch. They remain disabled by
default; pass `--exclude-disabled-plugins` only for a deliberately reduced build.

Before running the bot, copy `mybot/.env.example` to `mybot/.env` and set your own
API key, administrator IDs and group IDs. Runtime files are ignored by Git through
the included `.gitignore`.
"""

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?im)^(?:DEEPSEEK_API_KEY|OPENAI_API_KEY|API_KEY|TOKEN|SECRET|PASSWORD)[ \t]*=[ \t]*(?![ \t]*(?:#|$|your_|<))\S+"
    ),
    re.compile(r'get_env_int_list\("DAILY_GREET_GROUPS",\s*\[[^\]]+\]\)'),
)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _should_skip(path: Path, relative_path: Path, exclude_disabled_plugins: bool) -> bool:
    if relative_path in EXCLUDED_FILES:
        return True
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative_path.parts):
        return True
    if any(_is_within(relative_path, directory) for directory in EXCLUDED_RELATIVE_DIRECTORIES):
        return True
    if exclude_disabled_plugins and _is_within(relative_path, Path("mybot/plugins_disabled")):
        return True

    name = path.name.lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name.endswith(".log") or any(name.endswith(suffix) for suffix in EXCLUDED_COMPOUND_SUFFIXES):
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES


def _copy_source(source: Path, destination: Path, exclude_disabled_plugins: bool) -> None:
    for path in source.rglob("*"):
        relative_path = path.relative_to(source)
        if _should_skip(path, relative_path, exclude_disabled_plugins):
            continue
        target = destination / relative_path
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _remove_readonly(func, path: str, exc_info) -> None:
    Path(path).chmod(0o700)
    func(path)


def _clear_destination(destination: Path) -> None:
    for child in destination.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, onexc=_remove_readonly)
            continue
        child.chmod(0o700)
        child.unlink()


def _sanitize_release_config(destination: Path) -> None:
    config_path = destination / "mybot/common/config.py"
    config_text = config_path.read_text(encoding="utf-8")
    sanitized_text, replacements = re.subn(
        r'return get_env_int_list\("DAILY_GREET_GROUPS",\s*\[[^\]]*\]\)',
        'return get_env_int_list("DAILY_GREET_GROUPS")',
        config_text,
    )
    if replacements == 0 and 'return get_env_int_list("DAILY_GREET_GROUPS")' in config_text:
        sanitized_text = config_text
    elif replacements != 1:
        raise RuntimeError("could not sanitize DAILY_GREET_GROUPS fallback in public release")
    config_path.write_text(sanitized_text, encoding="utf-8")

    (destination / "mybot/.env.example").write_text(PUBLIC_ENV_TEMPLATE, encoding="utf-8")
    (destination / ".gitignore").write_text(PUBLIC_GITIGNORE, encoding="utf-8")
    (destination / "PUBLIC_RELEASE_MANIFEST.md").write_text(MANIFEST, encoding="utf-8")

    for path in (destination / "backups", destination / "mybot/data", destination / "mybot/logs"):
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").touch()


def _verify_release(destination: Path) -> None:
    forbidden_paths = (
        destination / ".git",
        destination / "mybot/.env",
        destination / "mybot/data/points.json",
        destination / "mybot/logs/bot.log",
    )
    present = [str(path.relative_to(destination)) for path in forbidden_paths if path.exists()]
    if present:
        raise RuntimeError(f"forbidden runtime files found in release: {', '.join(present)}")

    for path in destination.rglob("*"):
        relative_path = path.relative_to(destination)
        if path.is_file() and _should_skip(path, relative_path, exclude_disabled_plugins=False):
            if path.name != ".gitkeep":
                raise RuntimeError(f"excluded path found in release: {relative_path}")
        if not path.is_file() or path.suffix.lower() not in {".env", ".example", ".md", ".py", ".sh", ".toml", ".txt"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise RuntimeError(f"possible secret or private default found in release: {relative_path}")


def export_release(destination: Path, overwrite: bool, exclude_disabled_plugins: bool) -> None:
    source = PROJECT_ROOT.resolve()
    destination = destination.resolve()
    if destination == source or _is_within(source, destination) or _is_within(destination, source):
        raise ValueError("destination must be a separate sibling directory")

    if destination.exists():
        if not overwrite:
            raise FileExistsError(f"destination already exists: {destination}. Use --overwrite to replace it.")
        if any(destination.iterdir()):
            _clear_destination(destination)
    else:
        destination.mkdir(parents=True)
    _copy_source(source, destination, exclude_disabled_plugins)
    _sanitize_release_config(destination)
    _verify_release(destination)
    print(f"Public release exported to: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--overwrite", action="store_true", help="replace an existing destination directory")
    parser.add_argument(
        "--exclude-disabled-plugins",
        action="store_true",
        help="omit the legacy game plugin sources from the release",
    )
    args = parser.parse_args()
    export_release(args.destination, args.overwrite, args.exclude_disabled_plugins)


if __name__ == "__main__":
    main()
