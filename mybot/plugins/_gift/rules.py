"""Gift command parsing and deterministic business rules."""

import re

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from mybot.common.gift_store import GIFT_NAME_INDEX, GIFT_POOL

from .copy import DRINK_ALIASES, DRINK_STYLES, FLOWER_TIERS, SELF_TARGET_ALIASES

def _resolve_drink(raw_text: str) -> str | None:
    drink_name = raw_text.strip().split(maxsplit=1)[0] if raw_text.strip() else ""
    if drink_name in DRINK_STYLES:
        return drink_name
    return DRINK_ALIASES.get(drink_name)



def _ensure_drink_poem(story: str, drink_name: str) -> str:
    tail = story.strip()[-160:]
    if "『" in tail and "』" in tail:
        return story.strip()
    return f"{story.strip()}\n\n{DRINK_STYLES[drink_name]['poem']}"



def _select_shop_offer(shop: dict, selector: str) -> dict | None:
    text = selector.strip()
    if text in {"1", "2", "3"}:
        index = int(text) - 1
        offers = shop.get("offers", [])
        if 0 <= index < len(offers):
            return offers[index]
        return None

    gift = _resolve_gift_name(text)
    if not gift:
        return None
    return next((offer for offer in shop.get("offers", []) if offer["gift"]["id"] == gift["id"]), None)



def _resolve_gift_name(raw_text: str) -> dict | None:
    text = raw_text.strip()
    if not text:
        return None
    if text in GIFT_NAME_INDEX:
        return GIFT_NAME_INDEX[text]
    for item in GIFT_POOL:
        if item["name"] in text:
            return item
    return None


def _parse_gift_target(event: GroupMessageEvent, raw_text: str) -> tuple[str | None, str]:
    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq"))
            break

    cleaned_text = raw_text.strip()
    if target_id:
        return target_id, cleaned_text

    for alias in SELF_TARGET_ALIASES:
        if cleaned_text.startswith(alias):
            return event.get_user_id(), cleaned_text[len(alias):].strip()

    return None, cleaned_text


def _parse_flower_tier(raw_text: str) -> int | None:
    for amount, item in FLOWER_TIERS.items():
        if any(alias in raw_text for alias in item["aliases"]):
            return amount

    # 保留旧版数字用法，避免升级后已有习惯立即失效。
    amounts = re.findall(r"\d+", raw_text)
    if not amounts:
        return None
    amount = int(amounts[0])
    return amount if amount in FLOWER_TIERS else None



def calculate_tip_distribution(amount: int) -> tuple[int, int]:
    fee = amount // 5
    return fee, amount - fee
