import re

from mybot.common.ai_context import AIContextDatabase, AIContextRequest
from mybot.common.help_registry import CATEGORY_META, HelpItem, collect_help_items


_NAVIGATION_ITEMS = (
    HelpItem("系统说明", "/帮助 - 查看公开功能菜单", 5),
    HelpItem("趣味功能", "/游戏 - 查看历史小游戏玩法与开关", 5),
)

_CAPABILITY_QUERY_PATTERNS = (
    re.compile(r"(你|本猫|李太白给).{0,6}(会|能|可以).{0,8}(干啥|做啥|做什么|干什么|哪些|什么)"),
    re.compile(r"(你|本猫|李太白给).{0,6}(有什么|有啥|有哪).{0,4}(功能|命令|玩法|本事|招数)"),
    re.compile(r"(有哪些|有啥|有什么).{0,4}(命令|功能|玩法|指令|本事|招数)"),
    re.compile(r"(功能|命令|指令|菜单|玩法|帮助|用法|使用方法).{0,6}(介绍|说明|列表|大全|有哪些|有什么|有啥|怎么用|怎么玩)"),
    re.compile(r"(怎么|如何|怎样).{0,4}(用|使用|玩|操作).{0,8}(你|本猫|李太白给|这些|这个|那些)?"),
    re.compile(r"(介绍一下|说说|讲讲).{0,4}(你|本猫|李太白给).{0,8}(会|能|有什么|有啥)"),
    re.compile(r"(能|可以).{0,4}(帮我|替我)?.{0,6}(做什么|干什么|做啥|干啥|哪些事|什么事)"),
)

_FEATURE_HINTS = (
    "运势",
    "签到",
    "补签",
    "算卦",
    "作诗",
    "写诗",
    "藏头诗",
    "对联",
    "诗词接龙",
    "飞花令",
    "猜谜",
    "翻译",
    "总结",
    "润色",
    "解释",
    "凯撒",
    "摩斯",
    "base64",
    "url编码",
    "礼物",
    "图片库",
    "收图",
    "找图",
    "随机图",
    "送花",
    "代骂",
    "入典",
    "酒馆",
    "酒钱",
    "灵签翻盘",
    "墨宝寻踪",
    "观星",
    "情话",
    "表白",
    "借酒说话",
    "夸夸",
    "群管理",
    "小酌档",
    "雅集档",
    "天命档",
)

_USAGE_HINTS = (
    "会",
    "能",
    "可以",
    "有吗",
    "有没有",
    "有什么",
    "有啥",
    "有哪些",
    "怎么",
    "如何",
    "怎样",
    "用法",
    "玩法",
    "命令",
    "功能",
    "菜单",
    "帮助",
    "介绍",
    "说明",
)


def _compact_text(message: str) -> str:
    return re.sub(r"\s+", "", message).lower()


def should_reference_capability_prompt(message: str) -> bool:
    text = _compact_text(message)
    if not text:
        return False

    if any(pattern.search(text) for pattern in _CAPABILITY_QUERY_PATTERNS):
        return True

    if not any(hint in text for hint in _USAGE_HINTS):
        return False

    return any(feature in text for feature in _FEATURE_HINTS)


def _sorted_grouped_items(
    group_id: str | int | None = None,
    user_id: str | int | None = None,
) -> dict[str, list[HelpItem]]:
    grouped: dict[str, list[HelpItem]] = {}
    for _, _, item in collect_help_items(group_id, user_id):
        grouped.setdefault(item.category, []).append(item)
    for item in _NAVIGATION_ITEMS:
        grouped.setdefault(item.category, []).append(item)

    deduped: dict[str, list[HelpItem]] = {}
    for category, items in grouped.items():
        seen = set()
        unique_items = []
        for item in sorted(items, key=lambda row: (row.order, row.text)):
            if item.text in seen:
                continue
            seen.add(item.text)
            unique_items.append(item)
        deduped[category] = unique_items
    return deduped


def build_capability_prompt(
    group_id: str | int | None = None,
    user_id: str | int | None = None,
) -> str:
    grouped = _sorted_grouped_items(group_id, user_id)
    lines = [
        "本事簿使用规矩：",
        "1. 只挑当前问题最相关的公开功能简要介绍；范围太宽时可按分类概括，再提醒对方用 /帮助 或直接点名功能。",
        "2. 不要编造未公开的新功能，也不要把相似的普通请求误说成必须使用某条命令。",
        "3. 介绍能力时继续保持李太白给口吻，自称“本猫”，不要使用机械技术话术。",
        "",
        "公开能力索引：",
    ]

    sorted_categories = sorted(
        grouped,
        key=lambda category: (
            CATEGORY_META.get(category, {}).get("order", 999),
            category,
        ),
    )
    for category in sorted_categories:
        meta = CATEGORY_META.get(category, {})
        lines.append(f"[{category}]")
        if flavor := meta.get("flavor"):
            lines.append(flavor)
        lines.extend(f"- {item.text}" for item in grouped[category])
        lines.append("")

    return "\n".join(lines).rstrip()


def _matches_public_capability_database(request: AIContextRequest) -> bool:
    return should_reference_capability_prompt(request.message)


def _render_public_capability_database(request: AIContextRequest) -> str:
    return build_capability_prompt(request.group_id, request.user_id)


PUBLIC_CAPABILITY_DATABASE = AIContextDatabase(
    key="public_capabilities",
    title="《李太白给公开本事簿》",
    matcher=_matches_public_capability_database,
    renderer=_render_public_capability_database,
)
