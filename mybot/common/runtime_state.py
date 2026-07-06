from pathlib import Path

from mybot.common.json_store import load_json, mutate_json


RUNTIME_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "runtime_state.json"
DEFAULT_RUNTIME_STATE = {"bot_enabled": True}


def is_bot_enabled() -> bool:
    data = load_json(RUNTIME_STATE_FILE, DEFAULT_RUNTIME_STATE)
    value = data.get("bot_enabled", True) if isinstance(data, dict) else True
    return bool(value)


def set_bot_enabled(enabled: bool) -> bool:
    def mutator(data: dict) -> bool:
        data["bot_enabled"] = bool(enabled)
        return data["bot_enabled"]

    return mutate_json(RUNTIME_STATE_FILE, DEFAULT_RUNTIME_STATE, mutator)


def toggle_bot_enabled() -> bool:
    def mutator(data: dict) -> bool:
        current = bool(data.get("bot_enabled", True))
        data["bot_enabled"] = not current
        return data["bot_enabled"]

    return mutate_json(RUNTIME_STATE_FILE, DEFAULT_RUNTIME_STATE, mutator)
