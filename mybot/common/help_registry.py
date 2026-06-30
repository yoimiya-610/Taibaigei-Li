from dataclasses import dataclass
import sys
from types import ModuleType

from mybot.common.feature_flags import is_feature_enabled, module_feature_key


@dataclass(frozen=True)
class HelpItem:
    category: str
    text: str
    order: int = 100


CATEGORY_META = {
    "诗词文艺": {"icon": "📜", "order": 10, "flavor": "诗酒趁年华，想听什么雅兴，尽可向本猫开口。"},
    "情感互动": {"icon": "💕", "order": 20, "flavor": "人间情字难写，本猫替你磨墨润笔。"},
    "趣味功能": {"icon": "🎭", "order": 30, "flavor": "若想解闷寻笑，这一栏最会挑动兴致。"},
    "签到积分": {"icon": "📊", "order": 40, "flavor": "账本、名号、签到，都在这卷里慢慢翻。"},
    "社交互动": {"icon": "🎁", "order": 50, "flavor": "人情往来最讲究分寸，本猫替你把场面撑住。"},
    "小游戏": {"icon": "🎮", "order": 60, "flavor": "旧局新翻，图个热闹，莫把得失看得太重。"},
    "AI对话": {"icon": "💬", "order": 70, "flavor": "若有难题或心事，不妨与本猫对坐一谈。"},
    "系统说明": {"icon": "ℹ️", "order": 80, "flavor": "此处是门牌与路引，先认清本猫，再慢慢常来。"},
}


def _module_help_items(module: ModuleType) -> list[HelpItem]:
    raw_items = getattr(module, "HELP_ITEMS", ())
    items = []
    for item in raw_items:
        if isinstance(item, HelpItem):
            items.append(item)
        elif isinstance(item, dict):
            items.append(
                HelpItem(
                    category=item["category"],
                    text=item["text"],
                    order=item.get("order", 100),
                )
            )
    return items


def collect_help_items() -> list[tuple[str, int, HelpItem]]:
    collected = []
    for module_name, module in list(sys.modules.items()):
        if module_name.removeprefix("mybot.").startswith("plugins_disabled."):
            continue
        feature = module_feature_key(module_name)
        if not feature:
            continue
        if not is_feature_enabled(feature):
            continue
        for index, item in enumerate(_module_help_items(module)):
            collected.append((module_name, index, item))
    return collected


def render_help_menu() -> str:
    grouped: dict[str, list[tuple[str, int, HelpItem]]] = {}
    for module_name, index, item in collect_help_items():
        grouped.setdefault(item.category, []).append((module_name, index, item))

    lines = [
        "🎋 李太白给·功能菜单 🎋",
        "=" * 22,
        "（扶正墨镜）先试试 /运势，看看今日风月如何。",
        "=" * 22,
        "",
    ]

    sorted_categories = sorted(
        grouped,
        key=lambda category: (
            CATEGORY_META.get(category, {}).get("order", 999),
            category,
        ),
    )
    for category_index, category in enumerate(sorted_categories):
        meta = CATEGORY_META.get(category, {"icon": "🔹"})
        lines.append(f"{meta['icon']} 【{category}】")
        if flavor := meta.get("flavor"):
            lines.append(flavor)
        section_items = sorted(
            grouped[category],
            key=lambda row: (row[2].order, row[0], row[1], row[2].text),
        )
        example_items = section_items[:3]
        lines.extend(item.text for _, _, item in example_items)
        if len(section_items) > len(example_items):
            lines.append("……")
        if category_index != len(sorted_categories) - 1:
            lines.append("")

    lines.extend(
        [
            "",
            "细目可再问本猫，慢慢翻便是。",
            "『先从一签窥天色，再向百般门里游。』",
        ]
    )
    return "\n".join(lines)


def render_category_help(category: str) -> str | None:
    grouped: dict[str, list[tuple[str, int, HelpItem]]] = {}
    for module_name, index, item in collect_help_items():
        grouped.setdefault(item.category, []).append((module_name, index, item))

    if category not in grouped:
        return None

    meta = CATEGORY_META.get(category, {"icon": "🔹"})
    section_items = sorted(
        grouped[category],
        key=lambda row: (row[2].order, row[0], row[1], row[2].text),
    )

    lines = [
        f"{meta['icon']} 李太白给·{category}",
        "=" * 22,
    ]
    if flavor := meta.get("flavor"):
        lines.append(flavor)
        lines.append("=" * 22)

    lines.extend(item.text for _, _, item in section_items)
    lines.extend(
        [
            "=" * 22,
            "细则若还不够，再点一条来问本猫。",
            "『一卷先看门与目，真要入戏再深翻。』",
        ]
    )
    return "\n".join(lines)
