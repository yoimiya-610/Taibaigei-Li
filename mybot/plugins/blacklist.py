from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="blacklist",
    name="黑名单",
    default_enabled=True,
    scope="group",
    permission_level=5,
    data_files=("data/blacklist.json",),
    privacy_level="sensitive",
    backup_policy="standard",
)

from pathlib import Path

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.admin import has_command_permission, is_admin_user
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.json_store import load_json, mutate_json
from mybot.common.logger import get_plugin_logger
from mybot.common.message_utils import get_message_text, is_explicit_command_text


BOT_ROOT = Path(__file__).resolve().parent.parent
BLACKLIST_FILE = BOT_ROOT / "data" / "blacklist.json"
LEGACY_BLACKLIST_FILE = BOT_ROOT / "mybot" / "data" / "blacklist.json"
# 公开上游不内置私有运行条目；部署后通过运行数据维护。
BLACKLIST_WORDS = []
COMMAND_ALIASES = ("黑名单", "系统黑名单")
logger = get_plugin_logger(__name__)
_warned_legacy_paths: set[Path] = set()


def _active_blacklist_file() -> Path:
    if BLACKLIST_FILE.exists() or not LEGACY_BLACKLIST_FILE.exists():
        return BLACKLIST_FILE
    resolved = LEGACY_BLACKLIST_FILE.resolve()
    if resolved not in _warned_legacy_paths:
        logger.warning(
            "检测到旧黑名单路径，继续原位兼容读取 file=%s canonical=%s",
            resolved,
            BLACKLIST_FILE.resolve(),
        )
        _warned_legacy_paths.add(resolved)
    return LEGACY_BLACKLIST_FILE


def _default_data() -> dict:
    return {"system": list(BLACKLIST_WORDS), "groups": {}}


def _normalized_words(value) -> list[str]:
    if not isinstance(value, list):
        return []
    words: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not (word := item.strip()):
            continue
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            words.append(word)
    return words


def _load_data() -> dict:
    data = load_json(_active_blacklist_file(), _default_data())
    if not isinstance(data, dict):
        return _default_data()
    system = _normalized_words(data.get("system", BLACKLIST_WORDS))
    raw_groups = data.get("groups", {})
    if not isinstance(raw_groups, dict):
        raw_groups = {}
    groups = {
        str(group_id): _normalized_words(words)
        for group_id, words in raw_groups.items()
    }
    return {"system": system, "groups": groups}


def get_system_blacklist() -> list[str]:
    return _load_data()["system"]


def get_group_blacklist(group_id: str | int) -> list[str]:
    return _load_data()["groups"].get(str(group_id), [])


def _toggle_word(scope: str, word: str, group_id: str | int | None = None) -> bool:
    normalized = word.strip()
    if not normalized:
        raise ValueError("blacklist word cannot be empty")

    def mutate(data) -> bool:
        if not isinstance(data, dict):
            raise ValueError("blacklist data must be a mapping")
        data.setdefault("system", list(BLACKLIST_WORDS))
        data.setdefault("groups", {})
        if not isinstance(data["groups"], dict):
            data["groups"] = {}

        if scope == "system":
            words = _normalized_words(data["system"])
            data["system"] = words
        else:
            if group_id is None:
                raise ValueError("group blacklist requires a group id")
            group_key = str(group_id)
            words = _normalized_words(data["groups"].get(group_key, []))
            data["groups"][group_key] = words

        target = normalized.casefold()
        for index, existing in enumerate(words):
            if existing.casefold() == target:
                words.pop(index)
                return False
        words.append(normalized)
        return True

    return mutate_json(_active_blacklist_file(), _default_data(), mutate)


def toggle_system_blacklist(word: str) -> bool:
    return _toggle_word("system", word)


def toggle_group_blacklist(group_id: str | int, word: str) -> bool:
    return _toggle_word("group", word, group_id)


def check_blacklist(event: MessageEvent) -> bool:
    """只检查普通文本中的违禁词，不让命令参数或 @ 昵称触发。"""
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    if not is_feature_enabled("blacklist", group_id):
        return False

    message = get_message_text(event)
    if not message or is_explicit_command_text(message):
        return False

    words = get_system_blacklist()
    if group_id is not None:
        words.extend(get_group_blacklist(group_id))
    normalized_message = message.casefold()
    return any(word.casefold() in normalized_message for word in words)


def _render_blacklist(title: str, words: list[str]) -> str:
    if not words:
        return f"（翻开薄册）{title}尚无墨迹。"
    return f"（翻开薄册）{title}：\n" + "\n".join(
        f"{index}. {word}" for index, word in enumerate(words, start=1)
    )


blacklist_check = on_message(rule=Rule(check_blacklist), priority=1, block=True)
group_blacklist = on_command("黑名单", priority=3, block=True)
system_blacklist = on_command("系统黑名单", priority=3, block=True)


@blacklist_check.handle()
async def handle_blacklist():
    await blacklist_check.finish("关注悠依米亚喵，关注悠依米亚谢谢喵")


@group_blacklist.handle()
async def handle_group_blacklist(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await group_blacklist.finish("（合上薄册）群中禁字，只在对应群里落笔。")
    if not has_command_permission(event, "group_blacklist"):
        await group_blacklist.finish("（按住笔锋）此册只许四级以上的本群掌柜改动。")

    word = args.extract_plain_text().strip()
    if not word:
        await group_blacklist.finish(
            _render_blacklist("本群黑名单", get_group_blacklist(event.group_id))
        )
    added = toggle_group_blacklist(event.group_id, word)
    action = "添入" if added else "移出"
    await group_blacklist.finish(f"（薄册落墨）已将“{word}”{action}本群黑名单。")


@system_blacklist.handle()
async def handle_system_blacklist(event: MessageEvent, args: Message = CommandArg()):
    if not is_admin_user(event.get_user_id()):
        await system_blacklist.finish("（收起总册）此卷只交系统掌柜过目。")

    word = args.extract_plain_text().strip()
    if not word:
        await system_blacklist.finish(
            _render_blacklist("系统黑名单", get_system_blacklist())
        )
    added = toggle_system_blacklist(word)
    action = "添入" if added else "移出"
    await system_blacklist.finish(f"（总册落印）已将“{word}”{action}系统黑名单。")
