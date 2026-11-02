"""Extensible, read-mostly assembly for the personal scroll command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mybot.common.accounting import get_points, get_wine_money
from mybot.common.charm import get_charm
from mybot.common.gift_store import GIFT_POOL, get_gift_inventory_snapshot
from mybot.common.logger import get_plugin_logger
from mybot.common.public_contributions import get_public_contribution_stats
from mybot.common.titles import get_display_title


logger = get_plugin_logger(__name__)


@dataclass(frozen=True)
class PersonalScrollSection:
    lines: tuple[str, ...]


SectionBuilder = Callable[[str, str], PersonalScrollSection]


@dataclass(frozen=True)
class PersonalScrollProvider:
    key: str
    order: int
    build: SectionBuilder
    unavailable_line: str


class PersonalScrollRegistry:
    """Collect independently owned personal sections in a stable order."""

    def __init__(self) -> None:
        self._providers: dict[str, PersonalScrollProvider] = {}

    def register(self, provider: PersonalScrollProvider) -> None:
        key = provider.key.strip()
        if not key:
            raise ValueError("personal_scroll_provider_key_required")
        if key in self._providers:
            raise ValueError(f"duplicate_personal_scroll_provider: {key}")
        self._providers[key] = provider

    def collect(self, user_id: str, group_id: str) -> tuple[PersonalScrollSection, ...]:
        sections = []
        providers = sorted(self._providers.values(), key=lambda item: (item.order, item.key))
        for provider in providers:
            try:
                section = provider.build(user_id, group_id)
                if not isinstance(section, PersonalScrollSection) or not section.lines:
                    raise ValueError("invalid_personal_scroll_section")
            except Exception as exc:
                logger.exception(
                    f"卷册分段读取失败 provider={provider.key} group_id={group_id} user_id={user_id}: {exc}"
                )
                section = PersonalScrollSection((provider.unavailable_line,))
            sections.append(section)
        return tuple(sections)


def _points_section(user_id: str, group_id: str) -> PersonalScrollSection:
    points = get_points(user_id, group_id)
    return PersonalScrollSection(
        (f"💎 积分：当前 {int(points['current'])}｜累计获得 {int(points['total'])}",)
    )


def _wine_section(user_id: str, group_id: str) -> PersonalScrollSection:
    return PersonalScrollSection((f"🍶 酒钱：{get_wine_money(user_id, group_id)}",))


def _title_section(user_id: str, group_id: str) -> PersonalScrollSection:
    points = get_points(user_id, group_id)
    title = get_display_title(user_id, group_id, points)
    return PersonalScrollSection(
        (
            f"🎖 称号：{title['title']} [{title['rarity']}]",
            f"   名号入册：{title['unlocked_count']}/{title['total_count']}",
        )
    )


def _charm_section(user_id: str, group_id: str) -> PersonalScrollSection:
    return PersonalScrollSection((f"🌸 魅力：{get_charm(user_id, group_id)}",))


def _gift_section(user_id: str, group_id: str) -> PersonalScrollSection:
    record = get_gift_inventory_snapshot(user_id, group_id)
    items = record.get("items", {})
    labels = []
    total = 0
    known_ids = set()
    for gift in GIFT_POOL:
        gift_id = gift["id"]
        known_ids.add(gift_id)
        quantity = int(items.get(gift_id, 0))
        if quantity <= 0:
            continue
        total += quantity
        labels.append(f"{gift['icon']}{gift['name']}×{quantity}")

    unknown_quantities = [
        int(quantity)
        for gift_id, quantity in items.items()
        if gift_id not in known_ids and int(quantity) > 0
    ]
    if unknown_quantities:
        total += sum(unknown_quantities)
        labels.append(f"旧藏×{sum(unknown_quantities)}")

    if not labels:
        return PersonalScrollSection(("🎁 礼物：暂无",))

    lines = [f"🎁 礼物：{total} 件（{len(items)} 种）"]
    for index in range(0, len(labels), 4):
        lines.append(f"   {'｜'.join(labels[index:index + 4])}")
    return PersonalScrollSection(tuple(lines))


def _contribution_section(user_id: str, group_id: str) -> PersonalScrollSection:
    stats = get_public_contribution_stats(user_id, group_id)
    return PersonalScrollSection(
        (
            "🖋 公开贡献："
            f"入典 {stats['quote_speaker_count']} 条｜"
            f"执笔 {stats['quote_recorder_count']} 条｜"
            f"诗社 {stats['poetry_submission_count']} 篇｜"
            f"收图 {stats['image_saved_count']} 幅",
        )
    )


PERSONAL_SCROLL_REGISTRY = PersonalScrollRegistry()


def register_personal_scroll_provider(provider: PersonalScrollProvider) -> None:
    """Register a future personal system without changing the command plugin."""

    PERSONAL_SCROLL_REGISTRY.register(provider)


for _provider in (
    PersonalScrollProvider("points", 10, _points_section, "💎 积分：账页暂未翻明"),
    PersonalScrollProvider("wine", 20, _wine_section, "🍶 酒钱：账页暂未翻明"),
    PersonalScrollProvider("title", 30, _title_section, "🎖 称号：名册暂未翻明"),
    PersonalScrollProvider("charm", 40, _charm_section, "🌸 魅力：花名暂未翻明"),
    PersonalScrollProvider("gift", 50, _gift_section, "🎁 礼物：锦囊暂未翻明"),
    PersonalScrollProvider(
        "public_contributions",
        60,
        _contribution_section,
        "🖋 公开贡献：卷页暂未翻明",
    ),
):
    register_personal_scroll_provider(_provider)


def render_personal_scroll(
    user_id: str,
    group_id: str,
    nickname: str,
    *,
    registry: PersonalScrollRegistry = PERSONAL_SCROLL_REGISTRY,
) -> str:
    display_name = " ".join(str(nickname).split()) or str(user_id)
    if len(display_name) > 32:
        display_name = display_name[:31] + "…"
    lines = [
        "📜 李太白给·我的卷册 📜",
        "=" * 22,
        f"（本猫拂开长卷）{display_name} 的群中行迹，都收在这一页。",
        "=" * 22,
    ]
    for section in registry.collect(str(user_id), str(group_id)):
        lines.extend(section.lines)
    lines.extend(
        (
            "=" * 22,
            "『一卷收来身外数，\n"
            "几行记取袖中春。\n"
            "后来若有新章目，\n"
            "也向此间续旧闻。』",
        )
    )
    return "\n".join(lines)
