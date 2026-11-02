import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


# Load a local .env once so plugins can share the same env-based config.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_RETENTION_DAYS = 36500
MAX_BACKUP_KEEP_COUNT = 100000
MAX_IMAGE_FILE_MB = 50
MAX_IMAGE_GROUP_MB = 10240
MAX_IMAGE_GROUP_COUNT = 10000


@dataclass(frozen=True)
class RetentionSettings:
    group_chat_log_retention_days: int = 0
    backup_keep_days: int = 0
    backup_keep_count: int = 0
    backup_include_group_chat_logs: bool = True
    backup_include_image_library: bool = False
    errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def cleanup_enabled(self) -> bool:
        return any(
            (
                self.group_chat_log_retention_days > 0,
                self.backup_keep_days > 0,
                self.backup_keep_count > 0,
            )
        )


@dataclass(frozen=True)
class ImageLibrarySettings:
    ocr_enabled: bool = False
    max_file_bytes: int = 10 * 1024 * 1024
    max_group_bytes: int = 512 * 1024 * 1024
    max_group_images: int = 500


def get_deepseek_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def get_env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_env_float(name: str, default: float) -> float:
    raw_value = get_env_str(name)
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def get_env_int(name: str, default: int) -> int:
    raw_value = get_env_str(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def get_env_bool(name: str, default: bool = False) -> bool:
    raw_value = get_env_str(name).lower()
    if not raw_value:
        return default

    if raw_value in {"1", "true", "yes", "on", "y"}:
        return True
    if raw_value in {"0", "false", "no", "off", "n"}:
        return False
    return default


def get_env_int_list(name: str, default: Iterable[int] = ()) -> list[int]:
    raw_value = get_env_str(name)
    if not raw_value:
        return list(default)

    values = []
    for item in raw_value.replace("，", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def get_random_reply_chance() -> float:
    chance = get_env_float("RANDOM_REPLY_CHANCE", 0.01)
    return min(max(chance, 0.0), 1.0)


def get_daily_greet_groups() -> list[int]:
    return get_env_int_list("DAILY_GREET_GROUPS")


def get_backup_hour() -> int:
    return min(max(get_env_int("BACKUP_HOUR", 3), 0), 23)


def get_backup_minute() -> int:
    return min(max(get_env_int("BACKUP_MINUTE", 0), 0), 59)


def _bounded_nonnegative_env_int(name: str, maximum: int) -> tuple[int, str | None]:
    raw_value = get_env_str(name)
    if not raw_value:
        return 0, None
    try:
        value = int(raw_value)
    except ValueError:
        return 0, f"{name} 不是整数，已停用清理"
    if value < 0 or value > maximum:
        return 0, f"{name} 必须在 0 到 {maximum} 之间，已停用清理"
    return value, None


def _strict_env_bool(name: str, default: bool) -> tuple[bool, str | None]:
    raw_value = get_env_str(name)
    if not raw_value:
        return default, None
    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True, None
    if normalized in {"0", "false", "no", "off", "n"}:
        return False, None
    return default, f"{name} 不是有效布尔值，已采用安全默认值并停用清理"


def get_retention_settings() -> RetentionSettings:
    group_days, group_error = _bounded_nonnegative_env_int(
        "GROUP_CHAT_LOG_RETENTION_DAYS",
        MAX_RETENTION_DAYS,
    )
    backup_days, backup_days_error = _bounded_nonnegative_env_int(
        "BACKUP_KEEP_DAYS",
        MAX_RETENTION_DAYS,
    )
    backup_count, backup_count_error = _bounded_nonnegative_env_int(
        "BACKUP_KEEP_COUNT",
        MAX_BACKUP_KEEP_COUNT,
    )
    include_group_logs, include_error = _strict_env_bool(
        "BACKUP_INCLUDE_GROUP_CHAT_LOGS",
        True,
    )
    include_image_library, include_image_error = _strict_env_bool(
        "BACKUP_INCLUDE_IMAGE_LIBRARY",
        False,
    )
    errors = tuple(
        error
        for error in (
            group_error,
            backup_days_error,
            backup_count_error,
            include_error,
            include_image_error,
        )
        if error is not None
    )
    return RetentionSettings(
        group_chat_log_retention_days=group_days,
        backup_keep_days=backup_days,
        backup_keep_count=backup_count,
        backup_include_group_chat_logs=include_group_logs,
        backup_include_image_library=include_image_library,
        errors=errors,
    )


def _bounded_positive_env_int(name: str, default: int, maximum: int) -> int:
    value = get_env_int(name, default)
    return value if 1 <= value <= maximum else default


def get_image_library_settings() -> ImageLibrarySettings:
    max_file_mb = _bounded_positive_env_int(
        "IMAGE_LIBRARY_MAX_FILE_MB",
        10,
        MAX_IMAGE_FILE_MB,
    )
    max_group_mb = _bounded_positive_env_int(
        "IMAGE_LIBRARY_MAX_GROUP_MB",
        512,
        MAX_IMAGE_GROUP_MB,
    )
    max_group_images = _bounded_positive_env_int(
        "IMAGE_LIBRARY_MAX_GROUP_IMAGES",
        500,
        MAX_IMAGE_GROUP_COUNT,
    )
    return ImageLibrarySettings(
        ocr_enabled=get_env_bool("IMAGE_LIBRARY_OCR_ENABLED", False),
        max_file_bytes=max_file_mb * 1024 * 1024,
        max_group_bytes=max_group_mb * 1024 * 1024,
        max_group_images=max_group_images,
    )
