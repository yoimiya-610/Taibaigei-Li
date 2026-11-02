"""Wine-money persistence isolated from command and game rules."""

from pathlib import Path
from typing import Callable

from mybot.common.accounting import (
    add_wine_money as accounting_add_wine_money,
    get_points,
    get_wine_money as accounting_get_wine_money,
    refund_points,
    spend_points,
    spend_wine_money as accounting_spend_wine_money,
)


def get_wine_money(user_id: str, group_id: str, *, data_file: Path) -> int:
    return accounting_get_wine_money(user_id, group_id, store_path=data_file)


def add_wine_money(user_id: str, group_id: str, amount: int, *, data_file: Path) -> dict:
    return accounting_add_wine_money(user_id, group_id, amount, store_path=data_file)


def spend_wine_money(user_id: str, group_id: str, amount: int, *, data_file: Path) -> dict:
    return accounting_spend_wine_money(user_id, group_id, amount, store_path=data_file)


def exchange_points_to_wine(
    user_id: str,
    group_id: str,
    points_amount: int,
    *,
    data_file: Path,
    points_to_wine: Callable[[int], int],
    logger,
) -> dict:
    if points_amount <= 0:
        return {"status": "invalid_amount"}

    points_info = get_points(user_id, group_id)
    if points_info["current"] < points_amount:
        return {
            "status": "insufficient_points",
            "points_balance": points_info["current"],
            "point_cost": points_amount,
            "exchanged_wine": points_to_wine(points_amount),
        }
    if not spend_points(user_id, group_id, points_amount):
        return {"status": "point_spend_failed", "point_cost": points_amount}

    wine_amount = points_to_wine(points_amount)
    try:
        record = add_wine_money(user_id, group_id, wine_amount, data_file=data_file)
    except Exception as exc:
        refund_points(user_id, group_id, points_amount)
        logger.exception(f"太白酒馆兑换酒钱失败 group_id={group_id} user_id={user_id}: {exc}")
        return {"status": "store_error", "point_cost": points_amount}

    return {
        "status": "ok",
        "point_cost": points_amount,
        "exchanged_wine": wine_amount,
        "wine_balance": record["wine_money"],
    }


def prepare_wine_stake(
    user_id: str,
    group_id: str,
    stake_wine: int,
    *,
    data_file: Path,
    points_needed_for_wine: Callable[[int], int],
) -> dict:
    spend_result = spend_wine_money(user_id, group_id, stake_wine, data_file=data_file)
    if spend_result["ok"]:
        return {
            "status": "ok",
            "wine_balance": spend_result["balance"],
            "record": spend_result["record"],
        }

    shortfall = stake_wine - spend_result["balance"]
    return {
        "status": "insufficient_wine",
        "wine_balance": spend_result["balance"],
        "shortfall": shortfall,
        "point_cost": points_needed_for_wine(shortfall),
    }
