from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
import stat
from typing import Iterable, Sequence

from mybot.common.backup import (
    BACKUP_DIR,
    BOT_ROOT,
    DEFAULT_BACKUP_SOURCES,
    GROUP_CHAT_LOG_ROOT,
    BackupResult,
    create_verified_backup,
    is_link_or_reparse_point,
    verify_backup_archive,
    verify_backup_checksum,
)
from mybot.common.config import RetentionSettings, get_retention_settings


GROUP_ID_PATTERN = re.compile(r"[1-9]\d*")
YEAR_PATTERN = re.compile(r"\d{4}")
MONTH_PATTERN = re.compile(r"(?:0[1-9]|1[0-2])")
DAY_FILE_PATTERN = re.compile(r"(?:0[1-9]|[12]\d|3[01])\.yaml")
BACKUP_FILE_PATTERN = re.compile(r"bot_backup_(\d{8}_\d{6})\.tar\.gz")


class RetentionSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    observed_at: datetime
    size_bytes: int
    checksum_path: Path | None = None


@dataclass(frozen=True)
class CleanupPlan:
    kind: str
    root: Path
    candidates: tuple[CleanupCandidate, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def size_bytes(self) -> int:
        return sum(candidate.size_bytes for candidate in self.candidates)

    @property
    def date_range(self) -> tuple[date, date] | None:
        if not self.candidates:
            return None
        dates = [candidate.observed_at.date() for candidate in self.candidates]
        return min(dates), max(dates)


@dataclass(frozen=True)
class CleanupResult:
    kind: str
    deleted_count: int
    released_bytes: int
    date_range: tuple[date, date] | None


@dataclass(frozen=True)
class MaintenanceResult:
    group_logs: CleanupResult
    backups: CleanupResult


def _empty_result(kind: str) -> CleanupResult:
    return CleanupResult(kind, 0, 0, None)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _prepare_root(root: Path, kind: str) -> tuple[Path | None, tuple[str, ...]]:
    if not root.exists():
        return None, ()
    if is_link_or_reparse_point(root):
        return None, (f"{kind}根目录不能是链接或重解析点",)
    if not root.is_dir():
        return None, (f"{kind}根路径不是目录",)
    try:
        return root.resolve(strict=True), ()
    except OSError:
        return None, (f"{kind}根目录无法解析",)


def _regular_file_size(path: Path, root: Path) -> int:
    if is_link_or_reparse_point(path):
        raise RetentionSafetyError("候选是链接或重解析点")
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise RetentionSafetyError("候选不是普通文件")
    resolved = path.resolve(strict=True)
    if not _is_within(resolved, root):
        raise RetentionSafetyError("候选越过根目录边界")
    return metadata.st_size


def plan_group_chat_log_cleanup(
    root: Path = GROUP_CHAT_LOG_ROOT,
    *,
    retention_days: int,
    today: date | None = None,
) -> CleanupPlan:
    plan_root = root.absolute()
    if retention_days <= 0:
        return CleanupPlan("群聊日志", plan_root)

    resolved_root, errors = _prepare_root(root, "群聊日志")
    if errors or resolved_root is None:
        return CleanupPlan("群聊日志", plan_root, errors=errors)

    current_day = today or date.today()
    cutoff = current_day - timedelta(days=retention_days)
    candidates: list[CleanupCandidate] = []

    try:
        for group_dir in sorted(resolved_root.iterdir(), key=lambda item: item.name):
            if (
                is_link_or_reparse_point(group_dir)
                or not group_dir.is_dir()
                or not GROUP_ID_PATTERN.fullmatch(group_dir.name)
            ):
                continue
            for year_dir in sorted(group_dir.iterdir(), key=lambda item: item.name):
                if (
                    is_link_or_reparse_point(year_dir)
                    or not year_dir.is_dir()
                    or not YEAR_PATTERN.fullmatch(year_dir.name)
                ):
                    continue
                for month_dir in sorted(year_dir.iterdir(), key=lambda item: item.name):
                    if (
                        is_link_or_reparse_point(month_dir)
                        or not month_dir.is_dir()
                        or not MONTH_PATTERN.fullmatch(month_dir.name)
                    ):
                        continue
                    for log_file in sorted(month_dir.iterdir(), key=lambda item: item.name):
                        if (
                            is_link_or_reparse_point(log_file)
                            or not DAY_FILE_PATTERN.fullmatch(log_file.name)
                        ):
                            continue
                        try:
                            log_day = date(
                                int(year_dir.name),
                                int(month_dir.name),
                                int(log_file.stem),
                            )
                        except ValueError:
                            continue
                        if log_day >= cutoff or log_day >= current_day:
                            continue
                        size = _regular_file_size(log_file, resolved_root)
                        candidates.append(
                            CleanupCandidate(
                                path=log_file,
                                observed_at=datetime.combine(log_day, time.min),
                                size_bytes=size,
                            )
                        )
    except (OSError, RetentionSafetyError) as exc:
        return CleanupPlan(
            "群聊日志",
            resolved_root,
            errors=(f"群聊日志目录扫描异常: {exc}",),
        )

    return CleanupPlan(
        "群聊日志",
        resolved_root,
        tuple(sorted(candidates, key=lambda item: item.observed_at)),
    )


def plan_backup_cleanup(
    root: Path = BACKUP_DIR,
    *,
    keep_days: int,
    keep_count: int,
    now: datetime | None = None,
    protected_paths: Iterable[Path] = (),
) -> CleanupPlan:
    plan_root = root.absolute()
    if keep_days <= 0 and keep_count <= 0:
        return CleanupPlan("部署备份", plan_root)

    resolved_root, errors = _prepare_root(root, "备份")
    if errors or resolved_root is None:
        return CleanupPlan("部署备份", plan_root, errors=errors)

    protected = set()
    for path in protected_paths:
        try:
            protected.add(path.resolve(strict=True))
        except OSError:
            continue

    backups: list[CleanupCandidate] = []
    try:
        for path in resolved_root.iterdir():
            if is_link_or_reparse_point(path):
                continue
            match = BACKUP_FILE_PATTERN.fullmatch(path.name)
            if not match:
                continue
            try:
                observed_at = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
                resolved_path = path.resolve(strict=True)
                if resolved_path in protected:
                    continue
                size = _regular_file_size(path, resolved_root)
            except (OSError, ValueError, RetentionSafetyError):
                continue

            checksum_path = path.with_name(f"{path.name}.sha256")
            if checksum_path.exists() and not is_link_or_reparse_point(checksum_path):
                try:
                    size += _regular_file_size(checksum_path, resolved_root)
                except (OSError, RetentionSafetyError):
                    checksum_path = None
            else:
                checksum_path = None
            backups.append(
                CleanupCandidate(path, observed_at, size, checksum_path)
            )
    except OSError as exc:
        return CleanupPlan(
            "部署备份",
            resolved_root,
            errors=(f"备份目录扫描异常: {exc}",),
        )

    backups.sort(key=lambda item: (item.observed_at, item.path.name), reverse=True)
    current_time = now or datetime.now()
    cutoff = current_time - timedelta(days=keep_days)
    candidates: list[CleanupCandidate] = []
    for index, candidate in enumerate(backups):
        too_old = keep_days > 0 and candidate.observed_at < cutoff
        outside_count = keep_count > 0 and index >= keep_count
        if keep_days > 0 and keep_count > 0:
            delete = too_old and outside_count
        elif keep_days > 0:
            delete = too_old
        else:
            delete = outside_count
        if delete:
            candidates.append(candidate)

    return CleanupPlan("部署备份", resolved_root, tuple(candidates))


def _validate_group_candidate(candidate: CleanupCandidate, root: Path) -> None:
    relative = candidate.path.resolve(strict=True).relative_to(root)
    if len(relative.parts) != 4:
        raise RetentionSafetyError("群聊日志候选层级异常")
    group, year, month, filename = relative.parts
    if not (
        GROUP_ID_PATTERN.fullmatch(group)
        and YEAR_PATTERN.fullmatch(year)
        and MONTH_PATTERN.fullmatch(month)
        and DAY_FILE_PATTERN.fullmatch(filename)
    ):
        raise RetentionSafetyError("群聊日志候选格式异常")
    _regular_file_size(candidate.path, root)


def _validate_backup_candidate(candidate: CleanupCandidate, root: Path) -> None:
    if not BACKUP_FILE_PATTERN.fullmatch(candidate.path.name):
        raise RetentionSafetyError("备份候选格式异常")
    _regular_file_size(candidate.path, root)
    if candidate.checksum_path is not None:
        expected = candidate.path.with_name(f"{candidate.path.name}.sha256")
        if candidate.checksum_path != expected:
            raise RetentionSafetyError("备份校验文件名异常")
        _regular_file_size(candidate.checksum_path, root)


def _cleanup_empty_group_directories(path: Path, root: Path) -> None:
    current = path.parent
    while current != root:
        if is_link_or_reparse_point(current):
            return
        try:
            resolved = current.resolve(strict=True)
        except OSError:
            return
        if not _is_within(resolved, root):
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def apply_cleanup_plan(plan: CleanupPlan) -> CleanupResult:
    if not plan.is_valid:
        raise RetentionSafetyError("清理计划包含目录异常，拒绝执行")
    resolved_root, errors = _prepare_root(plan.root, plan.kind)
    if errors:
        raise RetentionSafetyError(errors[0])
    if resolved_root is None:
        if plan.candidates:
            raise RetentionSafetyError("清理根目录已消失")
        return _empty_result(plan.kind)

    for candidate in plan.candidates:
        if plan.kind == "群聊日志":
            _validate_group_candidate(candidate, resolved_root)
        elif plan.kind == "部署备份":
            _validate_backup_candidate(candidate, resolved_root)
        else:
            raise RetentionSafetyError("未知清理计划类型")

    for candidate in plan.candidates:
        candidate.path.unlink()
        if candidate.checksum_path is not None:
            candidate.checksum_path.unlink()
        if plan.kind == "群聊日志":
            _cleanup_empty_group_directories(candidate.path, resolved_root)

    return CleanupResult(
        kind=plan.kind,
        deleted_count=plan.candidate_count,
        released_bytes=plan.size_bytes,
        date_range=plan.date_range,
    )


def apply_retention_after_verified_backup(
    settings: RetentionSettings,
    backup: BackupResult,
    *,
    group_log_root: Path = GROUP_CHAT_LOG_ROOT,
    backup_root: Path = BACKUP_DIR,
    now: datetime | None = None,
) -> MaintenanceResult:
    if not settings.is_valid:
        raise RetentionSafetyError("保留配置无效，拒绝执行清理")
    if not settings.cleanup_enabled:
        return MaintenanceResult(_empty_result("群聊日志"), _empty_result("部署备份"))

    resolved_backup_root, errors = _prepare_root(backup_root, "备份")
    if errors or resolved_backup_root is None:
        raise RetentionSafetyError(errors[0] if errors else "备份根目录异常")
    if backup.path.parent.resolve(strict=True) != resolved_backup_root:
        raise RetentionSafetyError("本次新备份不在指定备份根目录内")
    verify_backup_archive(backup.path)
    if not verify_backup_checksum(backup.path, backup.checksum_path):
        raise RetentionSafetyError("本次新备份校验失败，拒绝执行清理")

    current_time = now or datetime.now()
    group_plan = plan_group_chat_log_cleanup(
        group_log_root,
        retention_days=settings.group_chat_log_retention_days,
        today=current_time.date(),
    )
    backup_plan = plan_backup_cleanup(
        backup_root,
        keep_days=settings.backup_keep_days,
        keep_count=settings.backup_keep_count,
        now=current_time,
        protected_paths=(backup.path,),
    )
    errors = group_plan.errors + backup_plan.errors
    if errors:
        raise RetentionSafetyError("；".join(errors))

    return MaintenanceResult(
        group_logs=apply_cleanup_plan(group_plan),
        backups=apply_cleanup_plan(backup_plan),
    )


def format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def describe_plan(plan: CleanupPlan) -> str:
    if plan.errors:
        return f"{plan.kind}: 扫描失败，0 个候选（{'；'.join(plan.errors)}）"
    date_range = plan.date_range
    range_text = (
        "无"
        if date_range is None
        else f"{date_range[0].isoformat()} 至 {date_range[1].isoformat()}"
    )
    return (
        f"{plan.kind}: {plan.candidate_count} 个候选，"
        f"日期范围 {range_text}，预计释放 {format_size(plan.size_bytes)}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="预览或执行群聊日志与备份保留策略")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只预览候选，不修改文件")
    mode.add_argument("--apply", action="store_true", help="生成并验证新备份后执行清理")
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_retention_settings()
    group_plan = plan_group_chat_log_cleanup(
        retention_days=settings.group_chat_log_retention_days,
    )
    backup_plan = plan_backup_cleanup(
        keep_days=settings.backup_keep_days,
        keep_count=settings.backup_keep_count,
    )
    print(describe_plan(group_plan))
    print(describe_plan(backup_plan))
    for error in settings.errors:
        print(f"配置诊断: {error}")

    if not args.apply:
        print("dry-run 完成，未修改任何文件。")
        return 0
    if not settings.is_valid:
        print("配置无效，未创建备份，也未删除任何文件。")
        return 2
    if not settings.cleanup_enabled:
        print("所有保留值均为 0，未创建备份，也未删除任何文件。")
        return 0

    backup = create_verified_backup(
        backup_dir=BACKUP_DIR,
        sources=DEFAULT_BACKUP_SOURCES,
        include_group_chat_logs=settings.backup_include_group_chat_logs,
        group_chat_log_root=GROUP_CHAT_LOG_ROOT,
        include_image_library=settings.backup_include_image_library,
    )
    result = apply_retention_after_verified_backup(settings, backup)
    print(
        f"正式清理完成：群聊日志 {result.group_logs.deleted_count} 个，"
        f"部署备份 {result.backups.deleted_count} 个，"
        f"释放 {format_size(result.group_logs.released_bytes + result.backups.released_bytes)}。"
    )
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
