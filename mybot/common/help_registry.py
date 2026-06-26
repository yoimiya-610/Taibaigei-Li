from dataclasses import dataclass
import sys
from types import ModuleType

from common.feature_flags import is_feature_enabled, module_feature_key


@dataclass(frozen=True)
class HelpItem:
    category: str
    text: str
    order: int = 100


CATEGORY_META = {
    "诗词文艺": {"icon": "📜", "order": 10},
    "情感互动": {"icon": "💕", "order": 20},
    "趣味功能": {"icon": "🎭", "order": 30},
    "签到积分": {"icon": "📊", "order": 40},
    "社交互动": {"icon": "🎁", "order": 50},
    "小游戏": {"icon": "🎮", "order": 60},
    "AI对话": {"icon": "💬", "order": 70},
    "系统说明": {"icon": "ℹ️", "order": 80},
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
        if module_name.startswith("plugins_disabled."):
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
        "（推墨镜）本猫能为阁下做什么？",
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
        section_items = sorted(
            grouped[category],
            key=lambda row: (row[2].order, row[0], row[1], row[2].text),
        )
        lines.extend(item.text for _, _, item in section_items)
        if category_index != len(sorted_categories) - 1:
            lines.append("")

    lines.extend(
        [
            "=" * 22,
            "『绝活虽多不傲娇，有事无事找本猫。\n诗词歌赋皆精妙，陪你解闷乐逍遥~』",
        ]
    )
    return "\n".join(lines)
