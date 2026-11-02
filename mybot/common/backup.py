from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
from typing import Iterable


BOT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_ROOT.parent
BACKUP_DIR = PROJECT_ROOT / "backups"
GROUP_CHAT_LOG_ROOT = BOT_ROOT / "data" / "group_chat_logs"
IMAGE_LIBRARY_ROOT = BOT_ROOT / "data" / "image_library"

DEFAULT_BACKUP_SOURCES = (
    (BOT_ROOT / "data", "data"),
    (BOT_ROOT / "plugins", "plugins"),
    (BOT_ROOT / ".env.example", ".env.example"),
)

SKIP_DIR_NAMES = {"__pycache__", ".git", ".venv", "venv"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


class BackupSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupResult:
    path: Path
    checksum_path: Path
    sha256: str
    member_count: int


def is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_DIR_NAMES or path.suffix in SKIP_SUFFIXES:
        return True
    return path.name.startswith(".env") and path.name != ".env.example"


def _is_excluded(path: Path, excluded_roots: tuple[Path, ...]) -> bool:
    absolute = path.absolute()
    return any(_is_within(absolute, root) for root in excluded_roots)


def _add_source(
    archive: tarfile.TarFile,
    source: Path,
    arcname: str,
    excluded_roots: tuple[Path, ...],
) -> int:
    if not source.exists():
        return 0
    if is_link_or_reparse_point(source):
        raise BackupSafetyError(f"备份源是链接或重解析点: {source}")

    source_root = source.resolve(strict=True)
    stack = [(source, PurePosixPath(arcname))]
    added_count = 0

    while stack:
        path, archive_name = stack.pop()
        if _should_skip(path) or _is_excluded(path, excluded_roots):
            continue
        if is_link_or_reparse_point(path):
            continue

        resolved = path.resolve(strict=True)
        if not _is_within(resolved, source_root):
            raise BackupSafetyError("备份候选越过了备份源边界")

        metadata = path.stat(follow_symlinks=False)
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            continue

        archive.add(path, arcname=archive_name.as_posix(), recursive=False)
        added_count += 1

        if stat.S_ISDIR(metadata.st_mode):
            children = sorted(path.iterdir(), key=lambda item: item.name, reverse=True)
            for child in children:
                stack.append((child, archive_name / child.name))

    return added_count


def verify_backup_archive(path: Path) -> int:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise BackupSafetyError("备份包包含不安全的成员路径")
        return len(members)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_path_for(backup_path: Path) -> Path:
    return backup_path.with_name(f"{backup_path.name}.sha256")


def verify_backup_checksum(backup_path: Path, checksum_path: Path | None = None) -> bool:
    checksum_file = checksum_path or checksum_path_for(backup_path)
    try:
        line = checksum_file.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return False
    parts = line.split()
    if len(parts) != 2 or parts[1] != backup_path.name:
        return False
    expected = parts[0].lower()
    return len(expected) == 64 and expected == calculate_sha256(backup_path)


def create_verified_backup(
    *,
    backup_dir: Path = BACKUP_DIR,
    sources: Iterable[tuple[Path, str]] = DEFAULT_BACKUP_SOURCES,
    include_group_chat_logs: bool = True,
    group_chat_log_root: Path = GROUP_CHAT_LOG_ROOT,
    include_image_library: bool = False,
    image_library_root: Path = IMAGE_LIBRARY_ROOT,
    now: datetime | None = None,
) -> BackupResult:
    if backup_dir.exists() and is_link_or_reparse_point(backup_dir):
        raise BackupSafetyError("备份根目录不能是链接或重解析点")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not backup_dir.is_dir() or is_link_or_reparse_point(backup_dir):
        raise BackupSafetyError("备份根目录异常")

    backup_root = backup_dir.resolve(strict=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"bot_backup_{timestamp}.tar.gz"
    checksum_path = checksum_path_for(backup_path)
    if backup_path.exists() or checksum_path.exists():
        raise FileExistsError(f"同名备份已经存在: {backup_path.name}")

    archive_fd, archive_temp_name = tempfile.mkstemp(
        prefix=".bot_backup_",
        suffix=".tmp",
        dir=backup_root,
    )
    os.close(archive_fd)
    archive_temp = Path(archive_temp_name)
    checksum_temp: Path | None = None
    final_created = False
    excluded_roots = tuple(
        path.absolute()
        for enabled, path in (
            (include_group_chat_logs, group_chat_log_root),
            (include_image_library, image_library_root),
        )
        if not enabled
    )

    try:
        with tarfile.open(archive_temp, "w:gz") as archive:
            for source, arcname in sources:
                _add_source(archive, source, arcname, excluded_roots)

        member_count = verify_backup_archive(archive_temp)
        sha256 = calculate_sha256(archive_temp)
        os.replace(archive_temp, backup_path)
        final_created = True

        checksum_fd, checksum_temp_name = tempfile.mkstemp(
            prefix=".bot_backup_checksum_",
            suffix=".tmp",
            dir=backup_root,
        )
        os.close(checksum_fd)
        checksum_temp = Path(checksum_temp_name)
        checksum_temp.write_text(
            f"{sha256}  {backup_path.name}\n",
            encoding="ascii",
        )
        os.replace(checksum_temp, checksum_path)
        checksum_temp = None

        if not verify_backup_checksum(backup_path, checksum_path):
            raise BackupSafetyError("备份校验值复核失败")
        return BackupResult(
            path=backup_path,
            checksum_path=checksum_path,
            sha256=sha256,
            member_count=member_count,
        )
    except Exception:
        archive_temp.unlink(missing_ok=True)
        if checksum_temp is not None:
            checksum_temp.unlink(missing_ok=True)
        if final_created:
            checksum_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)
        raise
