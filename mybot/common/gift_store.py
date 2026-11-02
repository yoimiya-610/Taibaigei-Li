import hashlib
import math
import random
from datetime import datetime
from pathlib import Path

from mybot.common.json_store import load_json, mutate_json


BOT_ROOT = Path(__file__).resolve().parent.parent
GIFT_INVENTORY_FILE = BOT_ROOT / "data" / "gift_inventory.json"

GIFT_POOL = (
    {
        "id": "milk_tea",
        "icon": "🧋",
        "name": "云顶奶茶",
        "rarity": "R",
        "weight": 16,
        "other_charm": 48,
        "self_charm": 24,
        "summary": "甜口续命，适合给自己或群友回一口元气。",
    },
    {
        "id": "rice_ball",
        "icon": "🍙",
        "name": "梅香饭团",
        "rarity": "R",
        "weight": 16,
        "other_charm": 38,
        "self_charm": 0,
        "summary": "小小一团，饱腹又暖心。",
    },
    {
        "id": "pudding",
        "icon": "🍮",
        "name": "焦糖布丁",
        "rarity": "R",
        "weight": 14,
        "other_charm": 42,
        "self_charm": 18,
        "summary": "舀开便是甜意，常拿来安抚苦闷。",
    },
    {
        "id": "candied_haw",
        "icon": "🍡",
        "name": "琥珀糖葫芦",
        "rarity": "R",
        "weight": 12,
        "other_charm": 40,
        "self_charm": 0,
        "summary": "一口脆响，最适合在群里逗人开心。",
    },
    {
        "id": "fried_chicken",
        "icon": "🍗",
        "name": "脆皮鸡腿",
        "rarity": "SR",
        "weight": 9,
        "other_charm": 64,
        "self_charm": 0,
        "summary": "香气横着走，适合投喂饥肠辘辘的群友。",
    },
    {
        "id": "noodle_bowl",
        "icon": "🍜",
        "name": "热汤面",
        "rarity": "SR",
        "weight": 9,
        "other_charm": 70,
        "self_charm": 36,
        "summary": "一碗热气下肚，连深夜都没那么冷。",
    },
    {
        "id": "small_cake",
        "icon": "🍰",
        "name": "月光小蛋糕",
        "rarity": "SR",
        "weight": 8,
        "other_charm": 76,
        "self_charm": 30,
        "summary": "适合庆祝，也适合无缘由地偏心一下。",
    },
    {
        "id": "toy_bear",
        "icon": "🧸",
        "name": "抱抱熊",
        "rarity": "SR",
        "weight": 6,
        "other_charm": 86,
        "self_charm": 0,
        "summary": "不顶饿，但很会哄人。",
    },
    {
        "id": "vinyl_record",
        "icon": "💿",
        "name": "旧唱片",
        "rarity": "SSR",
        "weight": 4,
        "other_charm": 112,
        "self_charm": 0,
        "summary": "转起来像一段旧月光，适合郑重地送人。",
    },
    {
        "id": "star_lantern",
        "icon": "🏮",
        "name": "星灯小盏",
        "rarity": "SSR",
        "weight": 3,
        "other_charm": 150,
        "self_charm": 54,
        "summary": "照人也照己，算是少数能给自己添魅力的好物。",
    },
    {
        "id": "perfume",
        "icon": "🫧",
        "name": "风月香水",
        "rarity": "SSR",
        "weight": 2,
        "other_charm": 224,
        "self_charm": 60,
        "summary": "一按便是满袖清风，送人自用都很体面。",
    },
    {
        "id": "flight_cup",
        "icon": "✈️",
        "name": "神秘的杯子",
        "rarity": "SSR",
        "shop_price": 200,
        "weight": 5,
        "other_charm": -20,
        "self_charm": 120,
        "summary": "只宜自己收下，若转手送人，反会惹得风波扫了几分风采。",
    },
    {
        "id": "crown",
        "icon": "👑",
        "name": "鎏金小冠",
        "rarity": "UR",
        "weight": 1,
        "other_charm": 280,
        "self_charm": 0,
        "summary": "稀罕物件，适合让人一夜之间风头正盛。",
    },
)
GIFT_BY_ID = {item["id"]: item for item in GIFT_POOL}
GIFT_NAME_INDEX = {item["name"]: item for item in GIFT_POOL}
DAILY_GIFT_SHOP_SIZE = 3
GIFT_SHOP_PRICE_PER_POINT_CHARM = 0.6
GIFT_SHOP_PRICE_SWING = 0.2


def _gift_inventory_key(group_id: str, user_id: str) -> str:
    return f"{group_id}_{user_id}"


def _gift_record(group_id: str, user_id: str) -> dict:
    return {
        "user_id": user_id,
        "group_id": group_id,
        "items": {},
        "last_draw_date": "",
        "last_draw_gift": "",
    }


def _shop_key(group_id: str) -> str:
    return str(group_id)


def _shop_seed(group_id: str, day_text: str) -> int:
    digest = hashlib.sha256(f"{group_id}:{day_text}:gift-shop".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _build_daily_shop_offers(group_id: str, day_text: str) -> list[dict]:
    rng = random.Random(_shop_seed(group_id, day_text))
    selected = rng.sample(list(GIFT_POOL), k=min(DAILY_GIFT_SHOP_SIZE, len(GIFT_POOL)))
    offers = []
    for gift in selected:
        fixed_price = gift.get("shop_price")
        if fixed_price is not None:
            multiplier = 1.0
            price = int(fixed_price)
        else:
            multiplier = round(rng.uniform(1 - GIFT_SHOP_PRICE_SWING, 1 + GIFT_SHOP_PRICE_SWING), 2)
            base_price = gift["other_charm"] / GIFT_SHOP_PRICE_PER_POINT_CHARM
            price = max(1, math.ceil(base_price * multiplier))
        offers.append(
            {
                "gift_id": gift["id"],
                "price": price,
                "multiplier": multiplier,
            }
        )
    offers.sort(key=lambda item: (item["price"], item["gift_id"]))
    return offers


def get_daily_gift_shop(group_id: str, user_id: str | None = None, *, now: datetime | None = None) -> dict:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    def mutator(data: dict) -> dict:
        shops = data.setdefault("daily_shop", {})
        key = _shop_key(group_id)
        record = shops.get(key)
        if not isinstance(record, dict) or record.get("date") != today:
            record = {
                "date": today,
                "offers": _build_daily_shop_offers(group_id, today),
            }
            shops[key] = record

        purchases = data.setdefault("daily_shop_purchases", {})
        purchased_gift_ids = sorted(
            str(purchase.get("gift_id"))
            for purchase_key, purchase in purchases.items()
            if str(purchase_key).startswith(f"{group_id}_{today}_{user_id}_") and isinstance(purchase, dict)
        ) if user_id else []
        return {
            "group_id": group_id,
            "date": today,
            "offers": [
                {
                    **offer,
                    "gift": GIFT_BY_ID[offer["gift_id"]],
                }
                for offer in record.get("offers", [])
                if offer.get("gift_id") in GIFT_BY_ID
            ],
            "purchase_count": sum(
                1
                for purchase_key in purchases
                if str(purchase_key).startswith(f"{group_id}_{today}_")
            ),
            "purchased_gift_ids": purchased_gift_ids,
        }

    return mutate_json(GIFT_INVENTORY_FILE, {}, mutator)


def weighted_gift_draw(rng: random.Random | None = None) -> dict:
    chooser = rng or random
    return chooser.choices(
        GIFT_POOL,
        weights=[item["weight"] for item in GIFT_POOL],
        k=1,
    )[0]


def get_gift_inventory(user_id: str, group_id: str) -> dict:
    key = _gift_inventory_key(group_id, user_id)

    def mutator(data: dict) -> dict:
        inventories = data.setdefault("inventories", {})
        record = inventories.setdefault(key, _gift_record(group_id, user_id))
        record.setdefault("items", {})
        record.setdefault("last_draw_date", "")
        record.setdefault("last_draw_gift", "")
        return {
            "user_id": record["user_id"],
            "group_id": record["group_id"],
            "items": dict(record.get("items", {})),
            "last_draw_date": record.get("last_draw_date", ""),
            "last_draw_gift": record.get("last_draw_gift", ""),
        }

    return mutate_json(GIFT_INVENTORY_FILE, {}, mutator)


def get_gift_inventory_snapshot(user_id: str, group_id: str) -> dict:
    """Read an inventory without creating an empty user record."""

    key = _gift_inventory_key(group_id, user_id)
    data = load_json(GIFT_INVENTORY_FILE, {})
    inventories = data.get("inventories", {}) if isinstance(data, dict) else {}
    record = inventories.get(key, {}) if isinstance(inventories, dict) else {}
    raw_items = record.get("items", {}) if isinstance(record, dict) else {}
    items = {}
    if isinstance(raw_items, dict):
        for gift_id, raw_quantity in raw_items.items():
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                continue
            if quantity > 0:
                items[str(gift_id)] = quantity
    return {
        "user_id": str(record.get("user_id") or user_id) if isinstance(record, dict) else str(user_id),
        "group_id": str(record.get("group_id") or group_id) if isinstance(record, dict) else str(group_id),
        "items": items,
        "last_draw_date": str(record.get("last_draw_date") or "") if isinstance(record, dict) else "",
        "last_draw_gift": str(record.get("last_draw_gift") or "") if isinstance(record, dict) else "",
    }


def draw_daily_gift(user_id: str, group_id: str, *, now: datetime | None = None, rng: random.Random | None = None) -> dict:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    selected = weighted_gift_draw(rng)
    key = _gift_inventory_key(group_id, user_id)

    def mutator(data: dict) -> dict:
        inventories = data.setdefault("inventories", {})
        record = inventories.setdefault(key, _gift_record(group_id, user_id))
        record.setdefault("items", {})
        if record.get("last_draw_date") == today:
            return {
                "status": "already_drawn",
                "gift_id": record.get("last_draw_gift", ""),
            }
        record["last_draw_date"] = today
        record["last_draw_gift"] = selected["id"]
        record["items"][selected["id"]] = int(record["items"].get(selected["id"], 0)) + 1
        return {
            "status": "ok",
            "gift_id": selected["id"],
            "quantity": int(record["items"][selected["id"]]),
        }

    result = mutate_json(GIFT_INVENTORY_FILE, {}, mutator)
    if result.get("status") == "ok":
        result["gift"] = GIFT_BY_ID[selected["id"]]
    else:
        drawn_id = result.get("gift_id", "")
        result["gift"] = GIFT_BY_ID.get(drawn_id)
    return result


def consume_gift_item(user_id: str, group_id: str, gift_id: str) -> dict:
    key = _gift_inventory_key(group_id, user_id)

    def mutator(data: dict) -> dict:
        inventories = data.setdefault("inventories", {})
        record = inventories.setdefault(key, _gift_record(group_id, user_id))
        record.setdefault("items", {})
        quantity = int(record["items"].get(gift_id, 0))
        if quantity <= 0:
            return {"status": "missing", "quantity": 0}
        if quantity == 1:
            record["items"].pop(gift_id, None)
            return {"status": "ok", "quantity": 0}
        record["items"][gift_id] = quantity - 1
        return {"status": "ok", "quantity": quantity - 1}

    return mutate_json(GIFT_INVENTORY_FILE, {}, mutator)


def add_gift_item(user_id: str, group_id: str, gift_id: str, amount: int = 1) -> dict:
    key = _gift_inventory_key(group_id, user_id)

    def mutator(data: dict) -> dict:
        inventories = data.setdefault("inventories", {})
        record = inventories.setdefault(key, _gift_record(group_id, user_id))
        record.setdefault("items", {})
        record["items"][gift_id] = int(record["items"].get(gift_id, 0)) + amount
        if record["items"][gift_id] <= 0:
            record["items"].pop(gift_id, None)
            return {"quantity": 0}
        return {"quantity": int(record["items"][gift_id])}

    return mutate_json(GIFT_INVENTORY_FILE, {}, mutator)


def purchase_daily_shop_gift(user_id: str, group_id: str, gift_id: str, *, now: datetime | None = None) -> dict:
    result = purchase_daily_shop_gifts(user_id, group_id, [gift_id], now=now)
    if result.get("status") == "ok" and result.get("results"):
        single = dict(result["results"][0])
        single["status"] = "ok"
        return single
    return {
        "status": result.get("status", "error"),
        "gift_id": gift_id,
        "price": int(result.get("price") or 0),
        "gift": GIFT_BY_ID.get(gift_id),
    }


def purchase_daily_shop_gifts(user_id: str, group_id: str, gift_ids: list[str], *, now: datetime | None = None) -> dict:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    def mutator(data: dict) -> dict:
        shops = data.setdefault("daily_shop", {})
        shop_key = _shop_key(group_id)
        record = shops.get(shop_key)
        if not isinstance(record, dict) or record.get("date") != today:
            record = {
                "date": today,
                "offers": _build_daily_shop_offers(group_id, today),
            }
            shops[shop_key] = record

        offers = {
            str(offer.get("gift_id")): offer
            for offer in record.get("offers", [])
            if isinstance(offer, dict) and str(offer.get("gift_id")) in GIFT_BY_ID
        }
        normalized_gift_ids: list[str] = []
        seen: set[str] = set()
        for gift_id in gift_ids:
            gift_id = str(gift_id)
            if gift_id and gift_id not in seen:
                normalized_gift_ids.append(gift_id)
                seen.add(gift_id)
        if not normalized_gift_ids:
            return {"status": "empty"}

        for gift_id in normalized_gift_ids:
            if gift_id not in offers:
                return {"status": "not_for_sale", "gift_id": gift_id}

        purchases = data.setdefault("daily_shop_purchases", {})
        for gift_id in normalized_gift_ids:
            purchase_key = f"{group_id}_{today}_{user_id}_{gift_id}"
            purchased = purchases.get(purchase_key)
            if isinstance(purchased, dict):
                return {
                    "status": "already_purchased",
                    "gift_id": gift_id,
                    "price": int(purchased.get("price") or 0),
                }

        inventories = data.setdefault("inventories", {})
        inventory_key = _gift_inventory_key(group_id, user_id)
        inventory = inventories.setdefault(inventory_key, _gift_record(group_id, user_id))
        inventory.setdefault("items", {})
        results = []
        total_price = 0
        for gift_id in normalized_gift_ids:
            offer = offers[gift_id]
            inventory["items"][gift_id] = int(inventory["items"].get(gift_id, 0)) + 1
            purchase_key = f"{group_id}_{today}_{user_id}_{gift_id}"
            purchases[purchase_key] = {
                "gift_id": gift_id,
                "price": int(offer["price"]),
                "bought_at": current.strftime("%Y-%m-%d %H:%M:%S"),
            }
            total_price += int(offer["price"])
            results.append(
                {
                    "gift_id": gift_id,
                    "price": int(offer["price"]),
                    "quantity": int(inventory["items"][gift_id]),
                }
            )
        return {
            "status": "ok",
            "results": results,
            "price": total_price,
        }

    result = mutate_json(GIFT_INVENTORY_FILE, {}, mutator)
    for item in result.get("results", []):
        gift_id = str(item.get("gift_id") or "")
        if gift_id in GIFT_BY_ID:
            item["gift"] = GIFT_BY_ID[gift_id]
    gift_id = str(result.get("gift_id") or "")
    if gift_id in GIFT_BY_ID:
        result["gift"] = GIFT_BY_ID[gift_id]
    return result
