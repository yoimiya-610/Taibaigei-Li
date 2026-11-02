from datetime import date, datetime
from pathlib import Path
import sys
from types import ModuleType

from mybot.common.json_store import load_json, mutate_json
from mybot.common.legacy_games import LEGACY_GAME_ORDER
from mybot.common.plugin_metadata import (
    DEFAULT_FEATURE_ENABLED,
    FEATURE_NAMES,
    canonical_feature_key,
    get_plugin_metadata_for_feature,
    get_plugin_metadata_for_module,
)


FEATURE_FLAGS_FILE = Path(__file__).resolve().parent.parent / "data" / "feature_flags.json"
LEGACY_GAME_OVERRIDES_FILE = Path(__file__).resolve().parent.parent / "data" / "legacy_game_overrides.json"
LEGACY_GAME_SET = set(LEGACY_GAME_ORDER)


def _load_flags() -> dict:
    return load_json(FEATURE_FLAGS_FILE, {"features": {}})


def _coerce_day(now: date | datetime | None = None) -> date:
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return datetime.now().date()


def _rotation_token(now: date | datetime | None = None) -> str:
    return _coerce_day(now).isoformat()


def get_legacy_rotation_day_name(now: date | datetime | None = None) -> str:
    day = _coerce_day(now)
    return ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[day.weekday()]


def is_legacy_game_scheduled(feature: str, now: date | datetime | None = None) -> bool:
    if feature not in LEGACY_GAME_SET:
        raise ValueError(f"unknown legacy feature: {feature}")
    return False


def _load_legacy_overrides() -> dict:
    return load_json(
        LEGACY_GAME_OVERRIDES_FILE,
        {"date": "", "overrides": {}, "groups": {}},
    )


def get_legacy_game_override(
    feature: str,
    now: date | datetime | None = None,
    group_id: str | int | None = None,
) -> bool | None:
    if feature not in LEGACY_GAME_SET:
        return None

    data = _load_legacy_overrides()
    if group_id is None:
        value = data.get("overrides", {}).get(feature)
    else:
        value = data.get("groups", {}).get(str(group_id), {}).get(feature)
    if isinstance(value, bool):
        return value
    return None


def get_legacy_game_enabled(
    feature: str,
    now: date | datetime | None = None,
    group_id: str | int | None = None,
) -> bool:
    override = get_legacy_game_override(feature, now, group_id)
    if override is not None:
        return override
    if group_id is not None:
        global_override = get_legacy_game_override(feature, now)
        if global_override is not None:
            return global_override
    return False


def get_legacy_game_status(
    feature: str,
    now: date | datetime | None = None,
    group_id: str | int | None = None,
) -> dict[str, str | bool]:
    scheduled = is_legacy_game_scheduled(feature, now)
    override = get_legacy_game_override(feature, now, group_id)
    enabled = get_legacy_game_enabled(feature, now, group_id)
    global_override = get_legacy_game_override(feature, now)
    if override is not None:
        mode = "本群"
    elif global_override is not None:
        mode = "全局" if group_id is not None else "人工"
    else:
        mode = "默认"
    return {
        "enabled": enabled,
        "scheduled": scheduled,
        "mode": mode,
    }


def get_feature_name(feature: str) -> str:
    feature = _canonical_feature(feature)
    return FEATURE_NAMES.get(feature, feature)


def _canonical_feature(feature: str) -> str:
    return canonical_feature_key(feature)


def is_feature_enabled(feature: str, group_id: str | int | None = None) -> bool:
    feature = _canonical_feature(feature)
    metadata = get_plugin_metadata_for_feature(feature)
    if metadata is not None and metadata.protected:
        return True
    if feature in LEGACY_GAME_SET:
        return get_legacy_game_enabled(feature, group_id=group_id)
    flags = _load_flags()
    if group_id is not None:
        group_value = flags.get("groups", {}).get(str(group_id), {}).get(feature)
        if isinstance(group_value, bool):
            return group_value
    feature_values = flags.get("features", {})
    if feature in feature_values:
        return bool(feature_values[feature])
    legacy_keys = metadata.legacy_feature_keys if metadata is not None else ()
    for alias in legacy_keys:
        if alias in feature_values:
            return bool(feature_values[alias])
    default = metadata.default_enabled if metadata is not None else True
    return bool(default)


def set_feature_enabled(
    feature: str,
    enabled: bool,
    group_id: str | int | None = None,
) -> None:
    feature = _canonical_feature(feature)
    metadata = get_plugin_metadata_for_feature(feature)
    if metadata is not None and metadata.protected and not enabled:
        raise ValueError("protected_feature")
    if feature in LEGACY_GAME_SET:
        token = _rotation_token()

        def legacy_mutator(data: dict) -> None:
            data["date"] = token
            data.setdefault("overrides", {})
            if group_id is None:
                data["overrides"][feature] = bool(enabled)
                for values in data.get("groups", {}).values():
                    values.pop(feature, None)
            else:
                data.setdefault("groups", {})
                data["groups"].setdefault(str(group_id), {})
                data["groups"][str(group_id)][feature] = bool(enabled)

        mutate_json(
            LEGACY_GAME_OVERRIDES_FILE,
            {"date": "", "overrides": {}, "groups": {}},
            legacy_mutator,
        )
        return

    def mutator(data: dict) -> None:
        data.setdefault("features", {})
        if group_id is None:
            data["features"][feature] = bool(enabled)
            for values in data.get("groups", {}).values():
                values.pop(feature, None)
        else:
            data.setdefault("groups", {})
            data["groups"].setdefault(str(group_id), {})
            data["groups"][str(group_id)][feature] = bool(enabled)

    mutate_json(FEATURE_FLAGS_FILE, {"features": {}}, mutator)


def module_feature_key(module_name: str) -> str | None:
    metadata = get_plugin_metadata_for_module(module_name)
    return metadata.feature_key if metadata is not None else None


def _module_aliases(module: ModuleType) -> list[str]:
    raw_aliases = getattr(module, "COMMAND_ALIASES", ())
    aliases = []
    seen = set()
    for alias in raw_aliases:
        if isinstance(alias, str):
            normalized = alias.strip()
            if normalized and normalized not in seen:
                aliases.append(normalized)
                seen.add(normalized)
    return aliases


def collect_features(group_id: str | int | None = None) -> list[dict]:
    from mybot.common.help_registry import module_has_help_items

    features = []
    for module_name, module in list(sys.modules.items()):
        feature = module_feature_key(module_name)
        if not feature:
            continue
        features.append(
            {
                "key": feature,
                "name": get_feature_name(feature),
                "enabled": is_feature_enabled(feature, group_id),
                "protected": bool(
                    (metadata := get_plugin_metadata_for_feature(feature))
                    and metadata.protected
                ),
                "aliases": _module_aliases(module),
                "public": module_has_help_items(module),
            }
        )

    features.sort(key=lambda item: (item["name"], item["key"]))
    return features


def resolve_feature(identifier: str) -> str | None:
    normalized = identifier.strip().lower()
    if not normalized:
        return None
    canonical = canonical_feature_key(normalized)
    if canonical != normalized:
        return canonical

    for item in collect_features():
        if item["key"].lower() == normalized:
            return item["key"]
        if item["name"].lower() == normalized:
            return item["key"]
        for alias in item["aliases"]:
            if alias.lower() == normalized:
                return item["key"]
    return None


def _normalize_message_text(message: str) -> str:
    text = message.strip()
    while text.startswith(("/", "／")):
        text = text[1:].lstrip()
    return text


def _matches_alias(text: str, alias: str) -> bool:
    if text == alias:
        return True
    if text.startswith(alias):
        rest = text[len(alias):]
        return bool(rest and rest[0].isspace())
    return False


def find_disabled_feature_for_message(
    message: str,
    group_id: str | int | None = None,
) -> str | None:
    text = _normalize_message_text(message)
    if not text:
        return None

    for module_name, module in list(sys.modules.items()):
        feature = module_feature_key(module_name)
        if not feature or is_feature_enabled(feature, group_id):
            continue
        for alias in _module_aliases(module):
            if _matches_alias(text, alias):
                return feature
    return None
