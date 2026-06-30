from datetime import date, datetime
from pathlib import Path
import sys
from types import ModuleType

from mybot.common.json_store import load_json, mutate_json


FEATURE_FLAGS_FILE = Path(__file__).resolve().parent.parent / "data" / "feature_flags.json"
LEGACY_GAME_OVERRIDES_FILE = Path(__file__).resolve().parent.parent / "data" / "legacy_game_overrides.json"
PROTECTED_FEATURES = {"admin_console"}
DISABLED_PLUGIN_FEATURES = {
    "blackjack": "legacy_blackjack",
    "dice": "legacy_dice",
    "race": "legacy_race",
    "roulette": "legacy_roulette",
    "slot": "legacy_slot",
}
DEFAULT_FEATURE_ENABLED = {
    "legacy_blackjack": False,
    "legacy_dice": False,
    "legacy_race": False,
    "legacy_roulette": False,
    "legacy_slot": False,
}
LEGACY_GAME_ORDER = (
    "legacy_slot",
    "legacy_dice",
    "legacy_blackjack",
    "legacy_race",
    "legacy_roulette",
)
LEGACY_GAME_SET = set(LEGACY_GAME_ORDER)

FEATURE_NAMES = {
    "admin_console": "管理员控制台",
    "ai_cache": "AI缓存",
    "ai_chat": "普通AI对话",
    "backup": "自动备份",
    "blacklist": "黑名单",
    "daily_greet": "每日问候",
    "fortune": "签到运势",
    "fun": "趣味功能",
    "game_disabled": "小游戏状态",
    "gift": "社交互动",
    "hello": "调试命令",
    "help": "帮助菜单",
    "legacy_blackjack": "纸牌点数",
    "legacy_dice": "点数方块",
    "legacy_race": "赛博竞速",
    "legacy_roulette": "多人转盘",
    "legacy_slot": "图案转盘",
    "love": "情感互动",
    "monthly_fame": "月度风云榜",
    "poem": "诗词文艺",
    "poetry_game": "飞花令",
    "points": "积分排行",
    "premium_chat": "Pro对话档位",
    "quotes": "群友语录本",
    "rate_limit": "频率限制",
    "riddle": "猜谜",
    "roast_target": "代骂",
    "youyimiya": "米亚介绍",
}


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

    day = _coerce_day(now)
    if day.weekday() >= 5:
        return True
    return LEGACY_GAME_ORDER[day.weekday()] == feature


def _load_legacy_overrides() -> dict:
    return load_json(LEGACY_GAME_OVERRIDES_FILE, {"date": "", "overrides": {}})


def get_legacy_game_override(feature: str, now: date | datetime | None = None) -> bool | None:
    if feature not in LEGACY_GAME_SET:
        return None

    data = _load_legacy_overrides()
    if data.get("date") != _rotation_token(now):
        return None

    value = data.get("overrides", {}).get(feature)
    if isinstance(value, bool):
        return value
    return None


def get_legacy_game_enabled(feature: str, now: date | datetime | None = None) -> bool:
    override = get_legacy_game_override(feature, now)
    if override is not None:
        return override
    return is_legacy_game_scheduled(feature, now)


def get_legacy_game_status(feature: str, now: date | datetime | None = None) -> dict[str, str | bool]:
    scheduled = is_legacy_game_scheduled(feature, now)
    override = get_legacy_game_override(feature, now)
    enabled = override if override is not None else scheduled
    mode = "人工" if override is not None else "轮换"
    return {
        "enabled": enabled,
        "scheduled": scheduled,
        "mode": mode,
    }


def get_feature_name(feature: str) -> str:
    return FEATURE_NAMES.get(feature, feature)


def is_feature_enabled(feature: str) -> bool:
    if feature in PROTECTED_FEATURES:
        return True
    if feature in LEGACY_GAME_SET:
        return get_legacy_game_enabled(feature)
    flags = _load_flags()
    default = DEFAULT_FEATURE_ENABLED.get(feature, True)
    return bool(flags.get("features", {}).get(feature, default))


def set_feature_enabled(feature: str, enabled: bool) -> None:
    if feature in PROTECTED_FEATURES and not enabled:
        raise ValueError("protected_feature")
    if feature in LEGACY_GAME_SET:
        token = _rotation_token()

        def legacy_mutator(data: dict) -> None:
            data["date"] = token
            data.setdefault("overrides", {})
            data["overrides"][feature] = bool(enabled)

        mutate_json(LEGACY_GAME_OVERRIDES_FILE, {"date": "", "overrides": {}}, legacy_mutator)
        return

    def mutator(data: dict) -> None:
        data.setdefault("features", {})
        data["features"][feature] = bool(enabled)

    mutate_json(FEATURE_FLAGS_FILE, {"features": {}}, mutator)


def module_feature_key(module_name: str) -> str | None:
    module_name = module_name.removeprefix("mybot.")
    if module_name.startswith("plugins_disabled."):
        module_key = module_name.rsplit(".", 1)[-1]
        return DISABLED_PLUGIN_FEATURES.get(module_key)
    if not module_name.startswith("plugins."):
        return None
    feature = module_name.rsplit(".", 1)[-1]
    if feature.startswith("_"):
        return None
    return feature


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


def collect_features() -> list[dict]:
    features = []
    for module_name, module in list(sys.modules.items()):
        feature = module_feature_key(module_name)
        if not feature:
            continue
        features.append(
            {
                "key": feature,
                "name": get_feature_name(feature),
                "enabled": is_feature_enabled(feature),
                "protected": feature in PROTECTED_FEATURES,
                "aliases": _module_aliases(module),
            }
        )

    features.sort(key=lambda item: (item["name"], item["key"]))
    return features


def resolve_feature(identifier: str) -> str | None:
    normalized = identifier.strip().lower()
    if not normalized:
        return None

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


def find_disabled_feature_for_message(message: str) -> str | None:
    text = _normalize_message_text(message)
    if not text:
        return None

    for module_name, module in list(sys.modules.items()):
        feature = module_feature_key(module_name)
        if not feature or is_feature_enabled(feature):
            continue
        for alias in _module_aliases(module):
            if _matches_alias(text, alias):
                return feature
    return None
