import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


# Load a local .env once so plugins can share the same env-based config.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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
    # Preserve the current deployed behavior unless explicitly overridden.
    return get_env_int_list("DAILY_GREET_GROUPS")


def get_backup_hour() -> int:
    return min(max(get_env_int("BACKUP_HOUR", 3), 0), 23)


def get_backup_minute() -> int:
    return min(max(get_env_int("BACKUP_MINUTE", 0), 0), 59)
