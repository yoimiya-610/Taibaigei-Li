import re
from collections.abc import Iterable
from dataclasses import dataclass

from mybot.common.ai_context import AIContextDatabase, AIContextRequest


@dataclass(frozen=True)
class PublicPlayGuideEntry:
    key: str
    keywords: tuple[str, ...]
    intents: tuple[str, ...]
    public_explanation: str
    related_commands: tuple[str, ...]


_REALTIME_STATUS_PATTERNS = (
    re.compile(r"(我|俺|本猫)?.{0,4}(有|剩|还剩|当前).{0,6}(多少|几).{0,3}(积分|酒钱|魅力|礼物|贡献)"),
    re.compile(r"(今天|今日).{0,4}(签过|签到过|领过|领取过|补签过)"),
    re.compile(r"(我|俺).{0,6}(签过|领过低保|低保领过|补签过)"),
    re.compile(r"(我的|我).{0,4}(称号|名号).{0,6}(有哪些|是什么|几个|多少|当前)"),
    re.compile(r"(我的|我).{0,4}(卷册|礼物|魅力|公开贡献).{0,6}(怎么看|查看|多少|有哪些|是什么|当前)"),
)


def _compact_text(message: str) -> str:
    return re.sub(r"\s+", "", message).lower()


def _contains_any(text: str, values: Iterable[str]) -> bool:
    return any(value.lower() in text for value in values)


def _has_definition_intent(entry: PublicPlayGuideEntry, text: str) -> bool:
    definition_after_topic = r".{0,6}(是啥|是什么|啥意思|什么意思|干嘛的|干什么的|有什么用|有啥用)"
    definition_before_topic = r"(什么是|啥叫|何为).{0,4}"
    return any(
        re.search(rf"{re.escape(keyword.lower())}{definition_after_topic}", text)
        or re.search(rf"{definition_before_topic}{re.escape(keyword.lower())}", text)
        for keyword in entry.keywords
    )


def is_realtime_status_query(message: str) -> bool:
    text = _compact_text(message)
    return bool(text) and any(pattern.search(text) for pattern in _REALTIME_STATUS_PATTERNS)


def entry_matches(entry: PublicPlayGuideEntry, message: str) -> bool:
    text = _compact_text(message)
    if not text:
        return False
    if not _contains_any(text, entry.keywords):
        return False
    return _contains_any(text, entry.intents) or _has_definition_intent(entry, text)


def _load_public_play_guide_entries() -> tuple[PublicPlayGuideEntry, ...]:
    from mybot.common.titles import PUBLIC_PLAY_GUIDES as TITLE_GUIDES
    from mybot.plugins.fortune import PUBLIC_PLAY_GUIDES as FORTUNE_GUIDES
    from mybot.plugins.points import PUBLIC_PLAY_GUIDES as POINT_GUIDES
    from mybot.plugins.taibai_tavern import PUBLIC_PLAY_GUIDES as TAVERN_GUIDES

    return tuple((*FORTUNE_GUIDES, *POINT_GUIDES, *TITLE_GUIDES, *TAVERN_GUIDES))


def select_public_play_guides(message: str) -> tuple[PublicPlayGuideEntry, ...]:
    entries = _load_public_play_guide_entries()
    matched = [entry for entry in entries if entry_matches(entry, message)]
    if is_realtime_status_query(message):
        matched.extend(
            entry for entry in entries if entry.key == "personal_realtime_status"
        )

    seen: set[str] = set()
    unique = []
    for entry in matched:
        if entry.key in seen:
            continue
        seen.add(entry.key)
        unique.append(entry)
    return tuple(unique)


def should_reference_public_play_guides(message: str) -> bool:
    return bool(select_public_play_guides(message))


def build_public_play_guide_context(message: str) -> str:
    entries = select_public_play_guides(message)
    if not entries:
        return ""

    lines = [
        "公开玩法详解使用规矩：",
        "1. 只回答本轮问题命中的玩法条目；没有写明的费用、概率、后台规则和个人数据不要猜。",
        "2. 若用户询问个人实时状态，只能引导使用相关查询命令，不要假装已经翻到账本。",
        "3. 回答继续保持李太白给口吻，自称“本猫”。",
        "",
        "命中条目：",
    ]
    for entry in entries:
        lines.extend(
            [
                f"[{entry.key}]",
                f"公开说明：{entry.public_explanation}",
                f"相关命令：{'；'.join(entry.related_commands)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _matches_public_play_guides(request: AIContextRequest) -> bool:
    return should_reference_public_play_guides(request.message)


def _render_public_play_guides(request: AIContextRequest) -> str:
    return build_public_play_guide_context(request.message)


PUBLIC_PLAY_GUIDE_DATABASE = AIContextDatabase(
    key="public_play_guides",
    title="《李太白给公开玩法详解》",
    matcher=_matches_public_play_guides,
    renderer=_render_public_play_guides,
)
