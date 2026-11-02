from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import json
from pathlib import Path
import re
import time
from typing import Any

from mybot.common.backup import (
    BACKUP_DIR,
    checksum_path_for,
    is_link_or_reparse_point,
    verify_backup_archive,
    verify_backup_checksum,
)
from mybot.common.config import get_retention_settings
from mybot.common.logger import get_plugin_logger
from mybot.common.plugin_metadata import (
    iter_loaded_plugin_modules,
    iter_plugin_metadata,
    validate_loaded_plugin_metadata,
)


logger = get_plugin_logger(__name__)

BOT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = BOT_ROOT / "data"
DATA_MANIFEST_SCHEMA_VERSION = 1
MAX_HEALTH_FILES = 500
BACKUP_FILE_PATTERN = re.compile(r"bot_backup_(\d{8}_\d{6})\.tar\.gz")


class DataFileKind(StrEnum):
    JSON = "json"
    YAML_TREE = "yaml_tree"
    IMAGE_LIBRARY = "image_library"


class DiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DataFileSpec:
    path: str
    schema_version: int
    kind: DataFileKind = DataFileKind.JSON
    version_key: str | None = None
    version_required: bool = False
    required_collection: str | None = None


DATA_FILE_MANIFEST = (
    DataFileSpec("data/admin_audit.json", 1, version_key="schema_version", version_required=True, required_collection="records"),
    DataFileSpec("data/admin_permissions.json", 1, version_key="version"),
    DataFileSpec("data/blacklist.json", 1),
    DataFileSpec("data/charm.json", 1),
    DataFileSpec("data/classics.json", 1),
    DataFileSpec("data/feature_flags.json", 1),
    DataFileSpec("data/flower_gifts.json", 1),
    DataFileSpec("data/fortune_data.json", 1),
    DataFileSpec("data/gift_inventory.json", 1),
    DataFileSpec("data/gift_title_stats.json", 1),
    DataFileSpec("data/group_activities.json", 1, version_key="version"),
    DataFileSpec("data/group_activity_archive.json", 1, version_key="version"),
    DataFileSpec("data/group_card_queue.json", 1, version_key="version"),
    DataFileSpec("data/group_card_sync.json", 1, version_key="version"),
    DataFileSpec("data/group_chat_logs", 1, kind=DataFileKind.YAML_TREE),
    DataFileSpec("data/group_essence.json", 1, version_key="version"),
    DataFileSpec("data/group_message_index.json", 1, version_key="version"),
    DataFileSpec("data/image_library", 1, kind=DataFileKind.IMAGE_LIBRARY),
    DataFileSpec("data/interaction_stats.json", 1),
    DataFileSpec("data/legacy_game_overrides.json", 1),
    DataFileSpec("data/monthly_fame.json", 1),
    DataFileSpec("data/paid_rounds.json", 1, version_key="version", version_required=True, required_collection="rounds"),
    DataFileSpec("data/poetry_society.json", 1, version_key="schema_version", version_required=True, required_collection="groups"),
    DataFileSpec("data/points.json", 1),
    DataFileSpec("data/runtime_state.json", 1),
    DataFileSpec("data/slot_stats.json", 1),
    DataFileSpec("data/taibai_tavern.json", 1),
    DataFileSpec("data/titles.json", 1),
)


EXPECTED_SCHEDULED_JOBS = {
    "daily_backup": "每日备份",
    "group_activity_deadlines": "活动截止",
    "group_card_sync_queue": "群名片同步",
    "monthly_fame": "月度风云榜",
    "morning_greet": "早安问候",
    "night_greet": "晚安问候",
    "poetry_society_weekly_settlement": "诗社周结卷",
}


@dataclass(frozen=True)
class DiagnosticIssue:
    severity: DiagnosticSeverity
    component: str
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class StorageReport:
    manifest_version: int
    manifest_entries: int
    existing_entries: int
    missing_entries: int
    checked_files: int
    checked_bytes: int
    scan_truncated: bool
    unknown_paths: tuple[str, ...]
    issues: tuple[DiagnosticIssue, ...]


@dataclass(frozen=True)
class TaskReport:
    expected_jobs: int
    registered_jobs: int
    missing_jobs: tuple[str, ...]
    paused_jobs: tuple[str, ...]
    scheduler_running: bool | None
    recovery_hooks_installed: bool
    unfinished_paid_rounds: int
    due_paid_rounds: int
    invalid_paid_rounds: int
    queued_card_jobs: int
    abnormal_card_jobs: int
    active_activity_timers: int
    abnormal_activity_timers: int
    issues: tuple[DiagnosticIssue, ...]


@dataclass(frozen=True)
class PluginReport:
    declared_plugins: int
    loaded_plugins: int
    manifest_paths: int
    issues: tuple[DiagnosticIssue, ...]


@dataclass(frozen=True)
class BackupReport:
    backup_count: int
    latest_name: str | None
    latest_at: datetime | None
    latest_checksum: str
    latest_archive: str
    retention_errors: tuple[str, ...]
    issues: tuple[DiagnosticIssue, ...]


@dataclass(frozen=True)
class AuditReport:
    retained_records: int
    dropped_records: int
    latest_at: str | None


@dataclass(frozen=True)
class SystemDiagnosticReport:
    generated_at: datetime
    storage: StorageReport
    tasks: TaskReport
    plugins: PluginReport
    backups: BackupReport
    audit: AuditReport

    @property
    def issues(self) -> tuple[DiagnosticIssue, ...]:
        return (
            self.storage.issues
            + self.tasks.issues
            + self.plugins.issues
            + self.backups.issues
        )


def iter_data_file_manifest() -> tuple[DataFileSpec, ...]:
    return DATA_FILE_MANIFEST


def _issue(
    severity: DiagnosticSeverity,
    component: str,
    code: str,
    message: str,
    path: str | None = None,
) -> DiagnosticIssue:
    return DiagnosticIssue(severity, component, code, message, path)


def _safe_stat_size(path: Path) -> int:
    try:
        return path.stat(follow_symlinks=False).st_size
    except OSError:
        return 0


def _read_json_document(
    path: Path,
    display_path: str,
    issues: list[DiagnosticIssue],
) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "unreadable_file",
                f"无法按 UTF-8 读取：{exc}",
                display_path,
            )
        )
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "invalid_json",
                f"JSON 损坏（第 {exc.lineno} 行第 {exc.colno} 列）",
                display_path,
            )
        )
        return None


def _validate_json_schema(
    data: Any,
    spec: DataFileSpec,
    display_path: str,
    issues: list[DiagnosticIssue],
) -> None:
    if not isinstance(data, dict):
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "invalid_root",
                "顶层结构应为对象",
                display_path,
            )
        )
        return

    if spec.version_key:
        version = data.get(spec.version_key)
        if version is None:
            if spec.version_required:
                issues.append(
                    _issue(
                        DiagnosticSeverity.ERROR,
                        "storage",
                        "missing_schema_version",
                        f"缺少 {spec.version_key}，清单支持 v{spec.schema_version}",
                        display_path,
                    )
                )
        elif isinstance(version, bool) or not isinstance(version, int) or version < 1:
            issues.append(
                _issue(
                    DiagnosticSeverity.ERROR,
                    "storage",
                    "invalid_schema_version",
                    f"{spec.version_key} 不是有效正整数",
                    display_path,
                )
            )
        elif version > spec.schema_version:
            issues.append(
                _issue(
                    DiagnosticSeverity.ERROR,
                    "storage",
                    "future_schema_version",
                    f"文件为 v{version}，当前代码仅支持到 v{spec.schema_version}",
                    display_path,
                )
            )

    if spec.required_collection:
        collection = data.get(spec.required_collection)
        expected_type = list if spec.required_collection == "images" else dict
        if not isinstance(collection, expected_type):
            issues.append(
                _issue(
                    DiagnosticSeverity.ERROR,
                    "storage",
                    "invalid_collection",
                    f"{spec.required_collection} 集合缺失或类型异常",
                    display_path,
                )
            )


def _check_utf8_yaml(path: Path, display_path: str, issues: list[DiagnosticIssue]) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")()
    first_text = ""
    try:
        with path.open("rb") as file:
            while chunk := file.read(64 * 1024):
                decoded = decoder.decode(chunk)
                if len(first_text) < 4096:
                    first_text += decoded[: 4096 - len(first_text)]
            decoder.decode(b"", final=True)
    except (OSError, UnicodeError) as exc:
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "invalid_yaml_encoding",
                f"YAML 日志无法按 UTF-8 读取：{exc}",
                display_path,
            )
        )
        return
    first_nonempty = next((line.strip() for line in first_text.splitlines() if line.strip()), "")
    if first_nonempty != "-" and not first_nonempty.startswith("- "):
        issues.append(
            _issue(
                DiagnosticSeverity.WARNING,
                "storage",
                "unexpected_yaml_shape",
                "YAML 日志未以记录列表开头",
                display_path,
            )
        )


def _walk_regular_files(root: Path) -> tuple[list[Path], int, tuple[str, ...]]:
    files: list[Path] = []
    total_bytes = 0
    scan_errors: list[str] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            scan_errors.append(f"{directory}: {exc}")
            continue
        for path in children:
            if is_link_or_reparse_point(path):
                continue
            try:
                if path.is_dir():
                    stack.append(path)
                elif path.is_file():
                    files.append(path)
                    total_bytes += path.stat(follow_symlinks=False).st_size
            except OSError as exc:
                scan_errors.append(f"{path}: {exc}")
    files.sort(key=lambda item: item.as_posix())
    return files, total_bytes, tuple(scan_errors)


def _inspect_yaml_tree(
    path: Path,
    display_path: str,
    limit: int,
    issues: list[DiagnosticIssue],
) -> tuple[int, int, bool]:
    files, total_bytes, scan_errors = _walk_regular_files(path)
    if scan_errors:
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "directory_scan_failed",
                f"目录中有 {len(scan_errors)} 处无法读取",
                display_path,
            )
        )
    yaml_files = [candidate for candidate in files if candidate.suffix.lower() in {".yaml", ".yml"}]
    for candidate in yaml_files[:limit]:
        relative = candidate.relative_to(path)
        parts = relative.parts
        candidate_display = f"{display_path}/{relative.as_posix()}"
        if len(parts) != 4 or not (
            parts[0].isdigit()
            and len(parts[1]) == 4
            and parts[1].isdigit()
            and len(parts[2]) == 2
            and parts[2].isdigit()
            and re.fullmatch(r"\d{2}\.ya?ml", parts[3], re.IGNORECASE)
        ):
            issues.append(
                _issue(
                    DiagnosticSeverity.WARNING,
                    "storage",
                    "unexpected_log_path",
                    "群聊日志路径不符合 群/年/月/日 结构",
                    candidate_display,
                )
            )
        _check_utf8_yaml(candidate, candidate_display, issues)
    return min(len(yaml_files), limit), total_bytes, len(yaml_files) > limit


def _inspect_image_library(
    path: Path,
    display_path: str,
    limit: int,
    issues: list[DiagnosticIssue],
) -> tuple[int, int, bool]:
    files, total_bytes, scan_errors = _walk_regular_files(path)
    if scan_errors:
        issues.append(
            _issue(
                DiagnosticSeverity.ERROR,
                "storage",
                "directory_scan_failed",
                f"目录中有 {len(scan_errors)} 处无法读取",
                display_path,
            )
        )
    index_files = [candidate for candidate in files if candidate.name == "index.json"]
    checked = 0
    for index_path in index_files[:limit]:
        relative = index_path.relative_to(path)
        candidate_display = f"{display_path}/{relative.as_posix()}"
        if len(relative.parts) != 2 or not relative.parts[0].isdigit():
            issues.append(
                _issue(
                    DiagnosticSeverity.WARNING,
                    "storage",
                    "unexpected_image_index_path",
                    "图片索引未位于数字群号目录下",
                    candidate_display,
                )
            )
        data = _read_json_document(index_path, candidate_display, issues)
        if data is not None:
            _validate_json_schema(
                data,
                DataFileSpec(candidate_display, 1, version_key="version", version_required=True, required_collection="images"),
                candidate_display,
                issues,
            )
        checked += 1

    try:
        group_dirs = [
            candidate
            for candidate in path.iterdir()
            if candidate.is_dir()
            and not is_link_or_reparse_point(candidate)
            and candidate.name.isdigit()
        ]
    except OSError:
        group_dirs = []
    indexed_groups = {candidate.parent.name for candidate in index_files}
    for group_dir in group_dirs:
        images_dir = group_dir / "images"
        if images_dir.exists() and group_dir.name not in indexed_groups:
            issues.append(
                _issue(
                    DiagnosticSeverity.WARNING,
                    "storage",
                    "missing_image_index",
                    "群图片目录存在但缺少 index.json",
                    f"{display_path}/{group_dir.name}",
                )
            )
    return checked, total_bytes, len(index_files) > limit


def inspect_storage(
    bot_root: Path = BOT_ROOT,
    *,
    max_directory_files: int = MAX_HEALTH_FILES,
) -> StorageReport:
    issues: list[DiagnosticIssue] = []
    existing = 0
    missing = 0
    checked_files = 0
    checked_bytes = 0
    truncated = False

    for spec in DATA_FILE_MANIFEST:
        path = bot_root / Path(spec.path)
        if not path.exists():
            missing += 1
            continue
        existing += 1
        if is_link_or_reparse_point(path):
            issues.append(
                _issue(
                    DiagnosticSeverity.ERROR,
                    "storage",
                    "symlink_data_path",
                    "运行数据路径不能是符号链接",
                    spec.path,
                )
            )
            continue
        if spec.kind is DataFileKind.JSON:
            if not path.is_file():
                issues.append(_issue(DiagnosticSeverity.ERROR, "storage", "not_a_file", "清单要求普通文件", spec.path))
                continue
            checked_files += 1
            checked_bytes += _safe_stat_size(path)
            data = _read_json_document(path, spec.path, issues)
            if data is not None:
                _validate_json_schema(data, spec, spec.path, issues)
            continue
        if not path.is_dir():
            issues.append(_issue(DiagnosticSeverity.ERROR, "storage", "not_a_directory", "清单要求目录", spec.path))
            continue
        if spec.kind is DataFileKind.YAML_TREE:
            count, size, limited = _inspect_yaml_tree(path, spec.path, max_directory_files, issues)
        else:
            count, size, limited = _inspect_image_library(path, spec.path, max_directory_files, issues)
        checked_files += count
        checked_bytes += size
        truncated = truncated or limited

    data_root = bot_root / "data"
    known_names = {Path(spec.path).parts[1] for spec in DATA_FILE_MANIFEST}
    unknown_paths: list[str] = []
    if data_root.is_dir():
        try:
            for candidate in sorted(data_root.iterdir(), key=lambda item: item.name):
                if candidate.name.startswith(".") or candidate.name in known_names:
                    continue
                unknown_paths.append(f"data/{candidate.name}")
        except OSError as exc:
            issues.append(_issue(DiagnosticSeverity.ERROR, "storage", "data_root_unreadable", f"数据根目录扫描失败：{exc}", "data"))
    if unknown_paths:
        issues.append(
            _issue(
                DiagnosticSeverity.WARNING,
                "storage",
                "unlisted_data_paths",
                f"发现 {len(unknown_paths)} 个未登记运行数据路径",
            )
        )

    return StorageReport(
        manifest_version=DATA_MANIFEST_SCHEMA_VERSION,
        manifest_entries=len(DATA_FILE_MANIFEST),
        existing_entries=existing,
        missing_entries=missing,
        checked_files=checked_files,
        checked_bytes=checked_bytes,
        scan_truncated=truncated,
        unknown_paths=tuple(unknown_paths),
        issues=tuple(issues),
    )


def _read_json_for_tasks(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _inspect_scheduler(scheduler: Any, issues: list[DiagnosticIssue]) -> tuple[int, tuple[str, ...], tuple[str, ...], bool | None]:
    if scheduler is None:
        issues.append(_issue(DiagnosticSeverity.ERROR, "tasks", "scheduler_unavailable", "计划任务调度器不可用"))
        return 0, tuple(EXPECTED_SCHEDULED_JOBS), (), None
    try:
        jobs = list(scheduler.get_jobs())
    except Exception as exc:
        issues.append(_issue(DiagnosticSeverity.ERROR, "tasks", "scheduler_unreadable", f"计划任务无法读取：{exc}"))
        return 0, tuple(EXPECTED_SCHEDULED_JOBS), (), None
    jobs_by_id = {str(getattr(job, "id", "")): job for job in jobs}
    missing = tuple(sorted(set(EXPECTED_SCHEDULED_JOBS) - set(jobs_by_id)))
    paused = tuple(
        sorted(
            job_id
            for job_id, job in jobs_by_id.items()
            if job_id in EXPECTED_SCHEDULED_JOBS and getattr(job, "next_run_time", object()) is None
        )
    )
    if missing:
        issues.append(_issue(DiagnosticSeverity.ERROR, "tasks", "missing_scheduled_jobs", f"缺少计划任务：{'、'.join(missing)}"))
    if paused:
        issues.append(_issue(DiagnosticSeverity.WARNING, "tasks", "paused_scheduled_jobs", f"计划任务已暂停：{'、'.join(paused)}"))
    state = getattr(scheduler, "state", None)
    running = getattr(scheduler, "running", None)
    if isinstance(state, int):
        scheduler_running = state == 1
        if state == 2:
            issues.append(
                _issue(
                    DiagnosticSeverity.WARNING,
                    "tasks",
                    "scheduler_paused",
                    "计划任务调度器处于暂停状态",
                )
            )
    else:
        scheduler_running = bool(running) if isinstance(running, bool) else None
    if scheduler_running is False:
        code = "scheduler_paused" if state == 2 else "scheduler_stopped"
        if code == "scheduler_stopped":
            issues.append(
                _issue(
                    DiagnosticSeverity.ERROR,
                    "tasks",
                    code,
                    "计划任务调度器未运行",
                )
            )
    return len(jobs), missing, paused, scheduler_running


def inspect_tasks(
    scheduler: Any = None,
    *,
    data_root: Path = DATA_ROOT,
    now_timestamp: float | None = None,
) -> TaskReport:
    issues: list[DiagnosticIssue] = []
    registered, missing, paused, scheduler_running = _inspect_scheduler(scheduler, issues)
    now_value = time.time() if now_timestamp is None else float(now_timestamp)

    unfinished = due = invalid_rounds = 0
    paid_data = _read_json_for_tasks(data_root / "paid_rounds.json")
    if isinstance(paid_data, dict):
        rounds = paid_data.get("rounds", {})
        if isinstance(rounds, dict):
            terminal = {"settled", "refunded", "expired"}
            valid = terminal | {"preparing", "active", "settling", "refunding"}
            for record in rounds.values():
                if not isinstance(record, dict) or record.get("state") not in valid:
                    invalid_rounds += 1
                    continue
                if record.get("state") in terminal:
                    continue
                unfinished += 1
                deadline = record.get("deadline_at")
                if deadline is not None:
                    try:
                        if float(deadline) <= now_value:
                            due += 1
                    except (TypeError, ValueError):
                        invalid_rounds += 1
        else:
            invalid_rounds += 1
    if unfinished:
        issues.append(
            _issue(
                DiagnosticSeverity.WARNING,
                "tasks",
                "unfinished_paid_rounds",
                f"发现 {unfinished} 个未完成付费回合，其中 {due} 个已到期",
                "data/paid_rounds.json",
            )
        )
    if invalid_rounds:
        issues.append(_issue(DiagnosticSeverity.ERROR, "tasks", "invalid_paid_rounds", f"发现 {invalid_rounds} 个结构或状态异常的付费回合", "data/paid_rounds.json"))

    queued_jobs = abnormal_card_jobs = 0
    card_data = _read_json_for_tasks(data_root / "group_card_queue.json")
    if isinstance(card_data, dict):
        jobs = card_data.get("jobs", {})
        if isinstance(jobs, dict):
            queued_jobs = len(jobs)
            for key, job in jobs.items():
                if not isinstance(job, dict):
                    abnormal_card_jobs += 1
                    continue
                try:
                    datetime.fromisoformat(str(job["due_at"]))
                    attempts = int(job.get("attempts", 0))
                except (KeyError, TypeError, ValueError):
                    abnormal_card_jobs += 1
                    continue
                expected_key = f"{job.get('group_id')}:{job.get('user_id')}"
                if str(key) != expected_key or attempts < 0 or attempts >= 8:
                    abnormal_card_jobs += 1
    if abnormal_card_jobs:
        issues.append(
            _issue(
                DiagnosticSeverity.WARNING,
                "tasks",
                "abnormal_card_jobs",
                f"群名片队列有 {abnormal_card_jobs} 个异常或反复失败任务",
                "data/group_card_queue.json",
            )
        )

    active_timers = abnormal_timers = 0
    activity_data = _read_json_for_tasks(data_root / "group_activities.json")
    if isinstance(activity_data, dict):
        groups = activity_data.get("groups", {})
        if isinstance(groups, dict):
            for group in groups.values():
                current = group.get("current") if isinstance(group, dict) else None
                if not isinstance(current, dict) or current.get("status") != "active":
                    continue
                deadline = current.get("deadline")
                if not deadline:
                    continue
                active_timers += 1
                try:
                    datetime.fromisoformat(str(deadline))
                except ValueError:
                    abnormal_timers += 1
    if abnormal_timers:
        issues.append(
            _issue(
                DiagnosticSeverity.WARNING,
                "tasks",
                "abnormal_activity_timers",
                f"活动队列有 {abnormal_timers} 个无效截止时间",
                "data/group_activities.json",
            )
        )

    try:
        from mybot.common.paid_rounds import recovery_hooks_installed

        hooks_installed = recovery_hooks_installed()
    except Exception:
        hooks_installed = False
    if not hooks_installed:
        issues.append(_issue(DiagnosticSeverity.ERROR, "tasks", "paid_recovery_missing", "付费回合恢复钩子未安装"))

    return TaskReport(
        expected_jobs=len(EXPECTED_SCHEDULED_JOBS),
        registered_jobs=registered,
        missing_jobs=missing,
        paused_jobs=paused,
        scheduler_running=scheduler_running,
        recovery_hooks_installed=hooks_installed,
        unfinished_paid_rounds=unfinished,
        due_paid_rounds=due,
        invalid_paid_rounds=invalid_rounds,
        queued_card_jobs=queued_jobs,
        abnormal_card_jobs=abnormal_card_jobs,
        active_activity_timers=active_timers,
        abnormal_activity_timers=abnormal_timers,
        issues=tuple(issues),
    )


def inspect_plugins() -> PluginReport:
    issues: list[DiagnosticIssue] = []
    metadata = iter_plugin_metadata()
    loaded = tuple(iter_loaded_plugin_modules())
    try:
        validate_loaded_plugin_metadata()
    except Exception as exc:
        issues.append(_issue(DiagnosticSeverity.ERROR, "plugins", "plugin_metadata_invalid", f"插件元信息不一致：{exc}"))

    manifest_paths = {spec.path for spec in DATA_FILE_MANIFEST}
    declared_paths = {path for item in metadata for path in item.data_files}
    missing_paths = sorted(declared_paths - manifest_paths)
    orphan_paths = sorted(manifest_paths - declared_paths)
    if missing_paths:
        issues.append(_issue(DiagnosticSeverity.ERROR, "plugins", "manifest_missing_paths", f"数据清单漏登记：{'、'.join(missing_paths)}"))
    if orphan_paths:
        issues.append(_issue(DiagnosticSeverity.ERROR, "plugins", "manifest_orphan_paths", f"数据清单无插件归属：{'、'.join(orphan_paths)}"))
    if len(loaded) != len(metadata):
        issues.append(_issue(DiagnosticSeverity.ERROR, "plugins", "plugin_count_mismatch", f"已加载 {len(loaded)} 个，已声明 {len(metadata)} 个"))
    return PluginReport(len(metadata), len(loaded), len(manifest_paths), tuple(issues))


def inspect_backups(
    backup_root: Path = BACKUP_DIR,
    *,
    deep_verify: bool = False,
    now: datetime | None = None,
) -> BackupReport:
    issues: list[DiagnosticIssue] = []
    settings = get_retention_settings()
    backups: list[tuple[datetime, Path]] = []
    if backup_root.exists() and is_link_or_reparse_point(backup_root):
        issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "backup_root_link", "备份路径不能是链接或重解析点", "backups"))
    elif backup_root.exists() and not backup_root.is_dir():
        issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "backup_root_invalid", "备份路径不是目录", "backups"))
    elif backup_root.is_dir():
        try:
            for path in backup_root.iterdir():
                match = BACKUP_FILE_PATTERN.fullmatch(path.name)
                if not match or not path.is_file() or is_link_or_reparse_point(path):
                    continue
                try:
                    backups.append((datetime.strptime(match.group(1), "%Y%m%d_%H%M%S"), path))
                except ValueError:
                    continue
        except OSError as exc:
            issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "backup_root_unreadable", f"备份目录无法读取：{exc}", "backups"))
    backups.sort(key=lambda item: (item[0], item[1].name), reverse=True)

    latest_name = None
    latest_at = None
    checksum_state = "none"
    archive_state = "unchecked"
    if not backups:
        issues.append(_issue(DiagnosticSeverity.WARNING, "backups", "no_backups", "尚未发现标准部署备份", "backups"))
    else:
        latest_at, latest_path = backups[0]
        latest_name = latest_path.name
        checksum_path = checksum_path_for(latest_path)
        if not checksum_path.is_file():
            checksum_state = "missing"
            issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "missing_checksum", "最新备份缺少 SHA-256 清单", f"backups/{latest_name}"))
        elif deep_verify:
            try:
                checksum_state = "valid" if verify_backup_checksum(latest_path, checksum_path) else "invalid"
            except OSError:
                checksum_state = "invalid"
            if checksum_state != "valid":
                issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "invalid_checksum", "最新备份校验值不一致", f"backups/{latest_name}"))
        else:
            checksum_state = "present"

        if deep_verify:
            try:
                verify_backup_archive(latest_path)
                archive_state = "valid"
            except Exception as exc:
                archive_state = "invalid"
                issues.append(_issue(DiagnosticSeverity.ERROR, "backups", "invalid_archive", f"最新备份无法安全打开：{exc}", f"backups/{latest_name}"))
        current = now or datetime.now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        if latest_at < current - timedelta(hours=48):
            issues.append(_issue(DiagnosticSeverity.WARNING, "backups", "stale_backup", "最新部署备份已超过 48 小时", f"backups/{latest_name}"))

    for error in settings.errors:
        issues.append(_issue(DiagnosticSeverity.WARNING, "backups", "retention_config_invalid", f"保留配置异常：{error}"))
    return BackupReport(
        backup_count=len(backups),
        latest_name=latest_name,
        latest_at=latest_at,
        latest_checksum=checksum_state,
        latest_archive=archive_state,
        retention_errors=settings.errors,
        issues=tuple(issues),
    )


def inspect_audit(data_root: Path = DATA_ROOT) -> AuditReport:
    data = _read_json_for_tasks(data_root / "admin_audit.json")
    if not isinstance(data, dict):
        return AuditReport(0, 0, None)
    records = data.get("records", [])
    retained = len(records) if isinstance(records, list) else 0
    try:
        dropped = max(0, int(data.get("dropped_records", 0)))
    except (TypeError, ValueError):
        dropped = 0
    latest_at = None
    if isinstance(records, list):
        for record in reversed(records):
            if isinstance(record, dict) and record.get("timestamp"):
                latest_at = str(record["timestamp"])
                break
    return AuditReport(retained, dropped, latest_at)


def build_system_diagnostic(
    scheduler: Any = None,
    *,
    bot_root: Path = BOT_ROOT,
    backup_root: Path = BACKUP_DIR,
    deep_backup_verify: bool = False,
    max_directory_files: int = MAX_HEALTH_FILES,
) -> SystemDiagnosticReport:
    return SystemDiagnosticReport(
        generated_at=datetime.now().astimezone(),
        storage=inspect_storage(bot_root, max_directory_files=max_directory_files),
        tasks=inspect_tasks(scheduler, data_root=bot_root / "data"),
        plugins=inspect_plugins(),
        backups=inspect_backups(backup_root, deep_verify=deep_backup_verify),
        audit=inspect_audit(bot_root / "data"),
    )


_startup_hook_installed = False
_last_startup_report: SystemDiagnosticReport | None = None


def get_last_startup_report() -> SystemDiagnosticReport | None:
    return _last_startup_report


def install_startup_health_check(driver: Any) -> None:
    global _startup_hook_installed
    if _startup_hook_installed:
        return
    _startup_hook_installed = True

    async def startup_health_check() -> None:
        global _last_startup_report
        try:
            from nonebot_plugin_apscheduler import scheduler
        except Exception:
            scheduler = None
        _last_startup_report = build_system_diagnostic(
            scheduler,
            deep_backup_verify=False,
            max_directory_files=100,
        )
        report = _last_startup_report
        logger.info(
            "启动只读健康检查完成：数据清单=%s 已存在=%s 文件检查=%s 计划任务=%s/%s 插件=%s/%s 备份=%s",
            report.storage.manifest_entries,
            report.storage.existing_entries,
            report.storage.checked_files,
            report.tasks.registered_jobs,
            report.tasks.expected_jobs,
            report.plugins.loaded_plugins,
            report.plugins.declared_plugins,
            report.backups.backup_count,
        )
        for item in report.issues:
            message = f"{item.component}:{item.code} {item.message}"
            if item.path:
                message = f"{message} path={item.path}"
            if item.severity is DiagnosticSeverity.ERROR:
                logger.error("启动健康检查：%s", message)
            else:
                logger.warning("启动健康检查：%s", message)

    driver.on_startup(startup_health_check)
