import json
from pathlib import Path

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from mybot.common.config import get_env_int_list, get_env_str
from mybot.common.json_store import load_json, mutate_json
from mybot.common.plugin_metadata import get_plugin_metadata_for_feature


ADMIN_PERMISSIONS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "admin_permissions.json"
)
MIN_GROUP_PERMISSION_LEVEL = 1
MAX_GROUP_PERMISSION_LEVEL = 5

PERMISSION_LEVEL_NAMES = {
    1: "账页访客",
    2: "闲卷执事",
    3: "群务掌柜",
    4: "重务掌柜",
    5: "首席掌柜",
}
COMMAND_PERMISSION_LEVELS = {
    "feature_list": 1,
    "feature_toggle": 2,
    "group_blacklist": 4,
}

def _parse_superusers_env() -> set[str]:
    raw_value = get_env_str("SUPERUSERS")
    if not raw_value:
        return set()
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, (list, tuple, set)):
        values = decoded
    else:
        values = raw_value.replace("，", ",").split(",")
    return {
        str(value).strip()
        for value in values
        if str(value).strip().isdigit() and int(str(value).strip()) > 0
    }


def get_admin_user_ids() -> set[str]:
    """Return immutable system administrators from environment variables only."""
    admin_ids = {str(user_id) for user_id in get_env_int_list("BOT_ADMINS")}
    admin_ids.update(_parse_superusers_env())
    return admin_ids


def is_admin_user(user_id: str | int) -> bool:
    return str(user_id) in get_admin_user_ids()


def normalize_id(value: str | int, field_name: str = "id") -> str:
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise ValueError(f"invalid_{field_name}")
    return str(int(normalized))


def normalize_permission_level(value: str | int) -> int:
    normalized = str(value).strip()
    if not normalized.isdigit():
        raise ValueError("invalid_permission_level")
    level = int(normalized)
    if not 0 <= level <= MAX_GROUP_PERMISSION_LEVEL:
        raise ValueError("invalid_permission_level")
    return level


def _coerce_stored_level(value) -> int:
    if isinstance(value, dict):
        value = value.get("level", 0)
    if isinstance(value, bool):
        return 0
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 0
    return level if MIN_GROUP_PERMISSION_LEVEL <= level <= MAX_GROUP_PERMISSION_LEVEL else 0


def _groups_from_data(data) -> dict:
    if not isinstance(data, dict):
        return {}
    groups = data.get("groups")
    if isinstance(groups, dict):
        return groups
    # Compatibility for an early/direct shape: {"群号": {"QQ号": 等级}}.
    return {
        key: value
        for key, value in data.items()
        if key != "version" and isinstance(value, dict)
    }


def get_group_permission_level(group_id: str | int, user_id: str | int) -> int:
    if is_admin_user(user_id):
        return MAX_GROUP_PERMISSION_LEVEL
    try:
        group_key = normalize_id(group_id, "group_id")
        user_key = normalize_id(user_id, "user_id")
    except ValueError:
        return 0
    data = load_json(ADMIN_PERMISSIONS_FILE, {"version": 1, "groups": {}})
    group_values = _groups_from_data(data).get(group_key, {})
    if not isinstance(group_values, dict):
        return 0
    return _coerce_stored_level(group_values.get(user_key))


def set_group_permission_level(
    group_id: str | int,
    user_id: str | int,
    level: str | int,
) -> int:
    group_key = normalize_id(group_id, "group_id")
    user_key = normalize_id(user_id, "user_id")
    normalized_level = normalize_permission_level(level)
    if is_admin_user(user_key):
        raise ValueError("system_admin_immutable")

    def mutator(data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("invalid_admin_permissions_data")
        existing_groups = _groups_from_data(data)
        if "groups" not in data:
            data.clear()
            data.update({"version": 1, "groups": existing_groups})
        data["version"] = 1
        groups = data.setdefault("groups", {})
        group_values = groups.setdefault(group_key, {})
        if not isinstance(group_values, dict):
            group_values = {}
            groups[group_key] = group_values
        if normalized_level == 0:
            group_values.pop(user_key, None)
            if not group_values:
                groups.pop(group_key, None)
        else:
            group_values[user_key] = normalized_level

    mutate_json(
        ADMIN_PERMISSIONS_FILE,
        {"version": 1, "groups": {}},
        mutator,
    )
    return normalized_level


def get_event_permission_level(event: MessageEvent) -> int:
    if is_admin_user(event.get_user_id()):
        return MAX_GROUP_PERMISSION_LEVEL
    if not isinstance(event, GroupMessageEvent):
        return 0
    return get_group_permission_level(event.group_id, event.get_user_id())


def has_group_permission(event: MessageEvent, minimum_level: int = 1) -> bool:
    return get_event_permission_level(event) >= minimum_level


def has_command_permission(event: MessageEvent, command: str) -> bool:
    required_level = COMMAND_PERMISSION_LEVELS.get(command)
    if required_level is None:
        raise ValueError(f"unknown_permission_command: {command}")
    return has_group_permission(event, required_level)


def is_group_admin(event: MessageEvent) -> bool:
    """Compatibility alias; OneBot owner/admin roles intentionally grant nothing."""
    return has_group_permission(event, MIN_GROUP_PERMISSION_LEVEL)


def get_feature_permission_level(feature: str) -> int | None:
    metadata = get_plugin_metadata_for_feature(feature)
    # Unknown future features remain fail-safe at level 3 until their metadata
    # is declared. The consistency test prevents shipped plugins reaching here.
    return metadata.permission_level if metadata is not None else 3


def can_manage_feature(event: MessageEvent, feature: str) -> bool:
    required_level = get_feature_permission_level(feature)
    if required_level is None:
        return is_admin_user(event.get_user_id())
    return has_group_permission(event, required_level)
