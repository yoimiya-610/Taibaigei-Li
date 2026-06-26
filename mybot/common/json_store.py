import copy
import json
import threading
from pathlib import Path
from typing import Callable, TypeVar

from common.logger import get_plugin_logger


T = TypeVar("T")
R = TypeVar("R")

logger = get_plugin_logger(__name__)
_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()


def _resolve(path: Path | str) -> Path:
    return Path(path).resolve()


def _get_lock(path: Path) -> threading.RLock:
    resolved = _resolve(path)
    with _locks_guard:
        if resolved not in _locks:
            _locks[resolved] = threading.RLock()
        return _locks[resolved]


def _default_copy(default: T) -> T:
    return copy.deepcopy(default)


def _read_json_unlocked(path: Path, default: T) -> T:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return _default_copy(default)
    except json.JSONDecodeError as exc:
        logger.exception(f"JSON 解析失败 file={path}: {exc}")
        return _default_copy(default)
    except Exception as exc:
        logger.exception(f"JSON 读取失败 file={path}: {exc}")
        return _default_copy(default)


def _write_json_unlocked(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp_path.replace(path)


def load_json(path: Path | str, default: T) -> T:
    resolved = _resolve(path)
    with _get_lock(resolved):
        return _read_json_unlocked(resolved, default)


def save_json(path: Path | str, data) -> None:
    resolved = _resolve(path)
    with _get_lock(resolved):
        _write_json_unlocked(resolved, data)


def mutate_json(path: Path | str, default: T, mutator: Callable[[T], R]) -> R:
    resolved = _resolve(path)
    with _get_lock(resolved):
        data = _read_json_unlocked(resolved, default)
        result = mutator(data)
        _write_json_unlocked(resolved, data)
        return result
