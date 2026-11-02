"""Paid-round orchestration for Taibai Tavern's RPS duel."""

import asyncio
import sys
import time

from nonebot.adapters.onebot.v11 import Bot, MessageSegment

from mybot.common.accounting import ASSET_WINE_MONEY
from mybot.common.logger import get_plugin_logger
from mybot.common.paid_rounds import PaidRoundService, new_round_id

from .rules import (
    FEATURE_KEY,
    QQRpsResultError,
    RPS_CHALLENGE_TIMEOUT_SECONDS,
    RPS_GAME_TYPE,
    RPS_RESULT_DEADLINE_SECONDS,
    _challenge_expired,
    _extract_message_id,
    _normalize_rps_result,
    _read_qq_rps_result,
    _rps_result_name,
    compare_rps,
)


logger = get_plugin_logger(__name__)
pending_rps_challenges: dict[str, dict] = {}
active_rps_duels: dict[str, dict] = {}
rps_duel_locks: dict[str, asyncio.Lock] = {}


def _entry_module():
    return sys.modules["mybot.plugins.taibai_tavern"]


def _round_service() -> PaidRoundService:
    return _entry_module()._round_service()


def get_wine_money(user_id: str, group_id: str) -> int:
    return _entry_module().get_wine_money(user_id, group_id)


def create_rps_duel_round(
    challenge: dict,
    *,
    service: PaidRoundService | None = None,
    now: float | None = None,
) -> dict:
    service = service or _round_service()
    current_time = time.time() if now is None else float(now)
    group_id = str(challenge["group_id"])
    challenger_id = str(challenge["challenger_id"])
    target_id = str(challenge["target_id"])
    stake_wine = int(challenge["stake_wine"])
    participant_order = [challenger_id, target_id]
    nicknames = {
        challenger_id: str(challenge["challenger_nickname"]),
        target_id: str(challenge["target_nickname"]),
    }
    game = {
        "group_id": group_id,
        "stake_wine": stake_wine,
        "participant_order": participant_order,
        "nicknames": nicknames,
        "qq_rps_rolls": [],
        "started_at": current_time,
    }
    round_id = new_round_id(RPS_GAME_TYPE)
    game["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=RPS_GAME_TYPE,
        mode="duel",
        group_id=group_id,
        creator_id=challenger_id,
        asset_type=ASSET_WINE_MONEY,
        feature_key=FEATURE_KEY,
        payload=game,
        participants=[
            {
                "user_id": participant_id,
                "amount": stake_wine,
                "metadata": {
                    "role": "duelist",
                    "nickname": nicknames[participant_id],
                    "position": index,
                },
            }
            for index, participant_id in enumerate(participant_order)
        ],
        deadline_at=current_time + RPS_RESULT_DEADLINE_SECONDS,
    )

    try:
        challenger_charge = service.freeze_participant(round_id, challenger_id)
        if not challenger_charge["ok"]:
            service.refund_round(round_id, reason="challenger_insufficient_wine")
            return {
                "status": "challenger_insufficient_wine",
                "user_id": challenger_id,
                "balance": challenger_charge["balance"],
                "game": game,
            }

        target_charge = service.freeze_participant(round_id, target_id)
        if not target_charge["ok"]:
            service.refund_round(round_id, reason="target_insufficient_wine")
            return {
                "status": "target_insufficient_wine",
                "user_id": target_id,
                "balance": target_charge["balance"],
                "game": game,
            }
    except Exception:
        try:
            service.refund_round(round_id, reason="duel_start_failed")
        except Exception as refund_exc:
            logger.exception(f"对饮猜拳开局异常退款失败 round_id={round_id}: {refund_exc}")
        raise

    active_rps_duels[group_id] = game
    return {
        "status": "ok",
        "game": game,
        "balances": {
            challenger_id: challenger_charge["balance"],
            target_id: target_charge["balance"],
        },
    }


async def _collect_qq_rps_results(
    bot: Bot,
    group_id: str,
    game: dict,
    service: PaidRoundService,
) -> dict[str, int]:
    participant_order = game.get("participant_order")
    if not isinstance(participant_order, list) or len(participant_order) != 2:
        raise QQRpsResultError("对饮猜拳参与顺序无效")

    rolls = game.setdefault("qq_rps_rolls", [])
    if not isinstance(rolls, list) or len(rolls) > len(participant_order):
        raise QQRpsResultError("付费回合中的 QQ 猜拳记录无效")

    if not game.get("qq_rps_intro_sent"):
        first_id, second_id = participant_order
        await bot.send_group_msg(
            group_id=int(group_id),
            message=(
                "🍶 太白酒馆·对饮猜拳 🍶\n"
                f"（本猫把两只青瓷盏排定先后）{game['nicknames'][first_id]} 先拳，"
                f"{game['nicknames'][second_id]} 后拳；接下来两枚 QQ 猜拳依次归属。\n"
                f"每人已封存：{game['stake_wine']} 酒钱"
            ),
        )
        game["qq_rps_intro_sent"] = True
        service.update_payload(game["round_id"], game)

    for index, participant_id in enumerate(participant_order):
        if index >= len(rolls):
            try:
                response = await bot.send_group_msg(
                    group_id=int(group_id),
                    message=MessageSegment("rps", {}),
                )
            except Exception as exc:
                raise QQRpsResultError(f"第 {index + 1} 枚 QQ 猜拳发送失败") from exc

            message_id = _extract_message_id(response)
            if message_id is None:
                raise QQRpsResultError(f"第 {index + 1} 枚 QQ 猜拳未返回消息 ID")
            rolls.append({"participant_id": participant_id, "message_id": message_id})
            service.update_payload(game["round_id"], game)

        roll = rolls[index]
        if (
            not isinstance(roll, dict)
            or str(roll.get("participant_id", "")) != participant_id
            or not str(roll.get("message_id", "")).strip()
        ):
            raise QQRpsResultError(f"第 {index + 1} 枚 QQ 猜拳记录无效")

        result = _normalize_rps_result(roll.get("result"))
        if result is None:
            result = await _read_qq_rps_result(bot, str(roll["message_id"]))
            roll["result"] = result
            service.update_payload(game["round_id"], game)

    return {str(roll["participant_id"]): int(roll["result"]) for roll in rolls}


async def _notify_qq_rps_pending(
    bot: Bot,
    group_id: str,
    game: dict,
    service: PaidRoundService,
) -> None:
    if game.get("qq_rps_pending_notified"):
        return
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=(
                "（本猫按住两只酒盏）拳影一时看不真切，此局与双方酒钱先封在账中；"
                "稍后只验方才两枚原拳，不会重新出拳或重复扣钱。"
            ),
        )
        game["qq_rps_pending_notified"] = True
        service.update_payload(game["round_id"], game)
    except Exception as exc:
        logger.exception(f"发送 QQ 猜拳待确认提示失败 group_id={group_id}: {exc}")


async def _settle_rps_duel(
    bot: Bot,
    group_id: str,
    *,
    service: PaidRoundService | None = None,
) -> bool:
    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        game = active_rps_duels.get(group_id)
        if game is None:
            return False

        service = service or _round_service()
        try:
            round_record = service.get_round(game["round_id"])
            if round_record.get("state") == "settled":
                active_rps_duels.pop(group_id, None)
                return True
            if round_record.get("state") in {"refunded", "expired"}:
                active_rps_duels.pop(group_id, None)
                return False

            results = await _collect_qq_rps_results(bot, group_id, game, service)
            first_id, second_id = game["participant_order"]
            comparison = compare_rps(results[first_id], results[second_id])
            winner_id = None if comparison == 0 else (first_id if comparison > 0 else second_id)
            stake_wine = int(game["stake_wine"])
            payouts = {first_id: 0, second_id: 0}
            if winner_id is None:
                payouts = {first_id: stake_wine, second_id: stake_wine}
            else:
                payouts[winner_id] = stake_wine * 2
            persisted_result = {
                "rps": [
                    {"user_id": participant_id, "result": results[participant_id]}
                    for participant_id in game["participant_order"]
                ],
                "winner_id": winner_id,
                "stake_wine": stake_wine,
            }
            service.prepare_settlement(
                game["round_id"],
                result=persisted_result,
                payouts=payouts,
            )
            service.settle_round(game["round_id"])
        except Exception as exc:
            logger.exception(f"QQ 猜拳结果尚未确认 group_id={group_id}: {exc}")
            await _notify_qq_rps_pending(bot, group_id, game, service)
            return False

        active_rps_duels.pop(group_id, None)
        first_id, second_id = game["participant_order"]
        first_name = game["nicknames"][first_id]
        second_name = game["nicknames"][second_id]
        first_balance = get_wine_money(first_id, group_id)
        second_balance = get_wine_money(second_id, group_id)
        if winner_id is None:
            verdict = (
                "两拳相同，本局和盏；双方封存的酒钱各自归还。\n"
                f"{first_name} 酒钱：{first_balance}\n"
                f"{second_name} 酒钱：{second_balance}"
            )
            poem = "双拳同落青瓷盏，\n未分高低各自还。\n且把输赢留月下，\n来时再饮一杯闲。"
        else:
            winner_name = game["nicknames"][winner_id]
            verdict = (
                f"胜者：{winner_name}\n"
                f"入账：{game['stake_wine'] * 2} 酒钱（本局净得 {game['stake_wine']}）\n"
                f"{first_name} 酒钱：{first_balance}\n"
                f"{second_name} 酒钱：{second_balance}"
            )
            poem = "两盏临风拳影开，\n一声胜负落金台。\n酒钱不入闲人袖，\n尽随豪客此番来。"

        try:
            await bot.send_group_msg(
                group_id=int(group_id),
                message=(
                    "🍶 太白酒馆·对饮猜拳结算 🍶\n"
                    f"{'=' * 20}\n"
                    f"{first_name}：{_rps_result_name(results[first_id])}\n"
                    f"{second_name}：{_rps_result_name(results[second_id])}\n"
                    f"{'=' * 20}\n"
                    f"{verdict}\n"
                    f"{'=' * 20}\n"
                    f"『{poem}』"
                ),
            )
        except Exception as exc:
            logger.exception(f"发送对饮猜拳结算消息失败 group_id={group_id}: {exc}")
        return True


async def _expire_pending_rps_challenge(bot: Bot, group_id: str, challenge_id: str) -> None:
    await asyncio.sleep(RPS_CHALLENGE_TIMEOUT_SECONDS)
    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        challenge = pending_rps_challenges.get(group_id)
        if challenge is None or challenge.get("challenge_id") != challenge_id:
            return
        pending_rps_challenges.pop(group_id, None)
        challenger_name = challenge["challenger_nickname"]
        target_name = challenge["target_nickname"]
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=(
                f"（本猫把凉下来的酒盏收回柜上）{target_name} 未在一炷短香内接盏，"
                f"{challenger_name} 此番邀拳作罢；尚未扣取任何酒钱。"
            ),
        )
    except Exception as exc:
        logger.exception(f"发送对饮猜拳邀约过期提示失败 group_id={group_id}: {exc}")
