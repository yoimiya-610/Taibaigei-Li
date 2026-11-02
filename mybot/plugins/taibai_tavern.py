from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="taibai_tavern",
    name="太白酒馆",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=(
        "data/paid_rounds.json",
        "data/points.json",
        "data/taibai_tavern.json",
    ),
    privacy_level="personal",
    backup_policy="standard",
)

import asyncio
import random
import time
from pathlib import Path

from nonebot import get_bots, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

from mybot.common.accounting import ASSET_WINE_MONEY
from mybot.common.logger import get_plugin_logger
from mybot.common.paid_rounds import (
    PaidRoundService,
    new_round_id,
    register_recovery_adapter,
)
from mybot.common.user_utils import get_nickname

from mybot.plugins._taibai_tavern import storage as _tavern_storage
from mybot.plugins._taibai_tavern.business import (
    active_rps_duels,
    pending_rps_challenges,
    rps_duel_locks,
    _collect_qq_rps_results,
    _expire_pending_rps_challenge,
    _notify_qq_rps_pending,
    _settle_rps_duel,
    create_rps_duel_round,
)
from mybot.plugins._taibai_tavern.copy import (
    COMMAND_ALIASES,
    HELP_ITEMS,
    PUBLIC_PLAY_GUIDES,
    _format_board,
    _format_ink_trace_options,
    _render_tavern_help,
    _status_line,
)
from mybot.plugins._taibai_tavern.rules import (
    BAD_SIGN_ONE_WEIGHT,
    BAD_SIGN_PRIOR_WEIGHTS,
    BAD_SIGN_TWO_WEIGHT,
    BAD_SIGN_ZERO_WEIGHT,
    COOLDOWN_TIME,
    FEATURE_KEY,
    FIXED_BAD_SIGN_COUNTS,
    FLIP_GAME_TYPE,
    INK_GAME_TYPE,
    INK_TRACE_IMAGES,
    INK_TRACE_OPTION_COUNTS,
    INK_TRACE_REWARD_TENTHS_BY_IMAGE,
    INK_TRACE_STARGAZE_TENTHS,
    INK_TRACE_TREASURE_NAMES,
    INK_TRACE_TREASURE_WEIGHTS,
    MODE_MULTIPLIER_TENTHS,
    POINT_TO_WINE,
    QQRpsResultError,
    RANDOM_MODE,
    REFUND_TENTHS,
    RPS_CHALLENGE_TIMEOUT_SECONDS,
    RPS_FETCH_ATTEMPTS,
    RPS_FETCH_DELAY_SECONDS,
    RPS_GAME_TYPE,
    RPS_RESULT_DEADLINE_SECONDS,
    RPS_RESULT_NAMES,
    SIGN_COUNT,
    _challenge_expired,
    _extract_message_id,
    _extract_rps_result,
    _normalize_rps_result,
    _posterior_weight_for_bad_count,
    _read_qq_rps_result,
    _rps_result_name,
    calculate_continue_expectation_wine,
    calculate_ink_trace_reward_wine,
    calculate_ink_trace_stargaze_cost,
    calculate_optimal_return_ratio,
    calculate_refund_wine,
    calculate_reward_wine,
    choose_bad_sign_count,
    choose_ink_trace_treasure,
    compare_rps,
    current_multiplier_text,
    get_ink_trace_reward_tenths,
    get_ink_trace_treasure_name,
    get_mode_bad_weights,
    get_mode_label,
    get_mode_multipliers,
    max_good_count_for_mode,
    mode_multiplier_text,
    new_ink_trace_game,
    new_sign_deck,
    parse_exchange_points,
    parse_ink_trace_guess,
    parse_rps_challenge_args,
    parse_sign_position,
    parse_start_args,
    parse_wine_money,
    points_needed_for_wine,
    points_to_wine,
    reveal_wrong_ink_trace_option,
)


logger = get_plugin_logger(__name__)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "taibai_tavern.json"

active_games: dict[str, dict] = {}
active_ink_traces: dict[str, dict] = {}
cooldown: dict[str, float] = {}


def _round_service() -> PaidRoundService:
    return PaidRoundService(ledger_paths={ASSET_WINE_MONEY: DATA_FILE})


def _personal_round_key(round_record: dict) -> str:
    return f"{round_record['group_id']}_{round_record['creator_id']}"


def _restore_flip_round(round_record: dict, service: PaidRoundService) -> None:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    active_games[_personal_round_key(round_record)] = game


def _flip_round_is_loaded(round_record: dict) -> bool:
    return active_games.get(_personal_round_key(round_record), {}).get("round_id") == round_record["round_id"]


def _discard_flip_round(round_record: dict, service: PaidRoundService) -> None:
    if _flip_round_is_loaded(round_record):
        active_games.pop(_personal_round_key(round_record), None)


def _restore_ink_round(round_record: dict, service: PaidRoundService) -> None:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    for participant_id, participant in round_record.get("participants", {}).items():
        metadata = participant.get("metadata", {})
        if metadata.get("role") != "auxiliary" or metadata.get("kind") != "stargaze":
            continue
        if participant.get("state") not in {"active", "settled"}:
            continue
        revealed = metadata.get("revealed")
        if revealed and not game.get("stargazed"):
            game.setdefault("excluded", []).append(revealed)
            game["stargazed"] = True
            service.update_payload(round_record["round_id"], game)
        if participant.get("state") == "active":
            service.settle_participant(round_record["round_id"], participant_id)
    active_ink_traces[_personal_round_key(round_record)] = game


def _ink_round_is_loaded(round_record: dict) -> bool:
    return active_ink_traces.get(_personal_round_key(round_record), {}).get("round_id") == round_record["round_id"]


def _discard_ink_round(round_record: dict, service: PaidRoundService) -> None:
    if _ink_round_is_loaded(round_record):
        active_ink_traces.pop(_personal_round_key(round_record), None)


def _restore_rps_round(round_record: dict, service: PaidRoundService) -> None:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    active_rps_duels[round_record["group_id"]] = game


def _rps_round_is_loaded(round_record: dict) -> bool:
    return active_rps_duels.get(round_record["group_id"], {}).get("round_id") == round_record["round_id"]


def _discard_rps_round(round_record: dict, service: PaidRoundService) -> None:
    if _rps_round_is_loaded(round_record):
        active_rps_duels.pop(round_record["group_id"], None)


def _connected_bot() -> Bot | None:
    return next(iter(get_bots().values()), None)


async def _settle_due_rps_round(round_record: dict, service: PaidRoundService) -> None:
    group_id = round_record["group_id"]
    if not _rps_round_is_loaded(round_record):
        _restore_rps_round(round_record, service)

    bot = _connected_bot()
    if bot is not None and await _settle_rps_duel(bot, group_id, service=service):
        return

    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        current = service.get_round(round_record["round_id"])
        if current.get("state") in {"settled", "refunded", "expired"}:
            active_rps_duels.pop(group_id, None)
            return
        if current.get("result") is not None:
            if bot is None:
                service.settle_round(round_record["round_id"])
                active_rps_duels.pop(group_id, None)
            return
        service.refund_round(round_record["round_id"], reason="qq_rps_result_timeout")
        active_rps_duels.pop(group_id, None)
    if bot is None:
        return
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=(
                "🍶 太白酒馆·对饮猜拳 🍶\n"
                "（本猫收起两枚看不真切的拳影）此局未能在时限内验明，双方酒钱已原路归壶。\n"
                "『拳影未明休记账，杯中旧钱各自还。』"
            ),
        )
    except Exception as exc:
        logger.exception(f"发送对饮猜拳超时退款提示失败 group_id={group_id}: {exc}")


register_recovery_adapter(
    FLIP_GAME_TYPE,
    restore=_restore_flip_round,
    is_loaded=_flip_round_is_loaded,
    discard=_discard_flip_round,
)
register_recovery_adapter(
    INK_GAME_TYPE,
    restore=_restore_ink_round,
    is_loaded=_ink_round_is_loaded,
    discard=_discard_ink_round,
)
register_recovery_adapter(
    RPS_GAME_TYPE,
    restore=_restore_rps_round,
    is_loaded=_rps_round_is_loaded,
    discard=_discard_rps_round,
    on_due=_settle_due_rps_round,
)


def _game_key(event: GroupMessageEvent) -> str:
    return f"{event.group_id}_{event.get_user_id()}"


def get_wine_money(user_id: str, group_id: str) -> int:
    return _tavern_storage.get_wine_money(user_id, group_id, data_file=DATA_FILE)


def add_wine_money(user_id: str, group_id: str, amount: int) -> dict:
    return _tavern_storage.add_wine_money(user_id, group_id, amount, data_file=DATA_FILE)


def spend_wine_money(user_id: str, group_id: str, amount: int) -> dict:
    return _tavern_storage.spend_wine_money(user_id, group_id, amount, data_file=DATA_FILE)


def exchange_points_to_wine(user_id: str, group_id: str, points_amount: int) -> dict:
    return _tavern_storage.exchange_points_to_wine(
        user_id,
        group_id,
        points_amount,
        data_file=DATA_FILE,
        points_to_wine=points_to_wine,
        logger=logger,
    )


def prepare_wine_stake(user_id: str, group_id: str, stake_wine: int) -> dict:
    return _tavern_storage.prepare_wine_stake(
        user_id,
        group_id,
        stake_wine,
        data_file=DATA_FILE,
        points_needed_for_wine=points_needed_for_wine,
    )


tavern = on_command("太白酒馆", aliases={"酒馆", "酒馆玩法"}, priority=5, block=True)
wine_balance = on_command("酒钱", aliases={"我的酒钱", "酒钱余额"}, priority=5, block=True)
exchange_wine = on_command("兑换酒钱", aliases={"换酒钱", "添酒钱"}, priority=5, block=True)
start_flip = on_command("灵签翻盘", aliases={"灵签"}, priority=5, block=True)
reveal_sign = on_command("翻签", priority=5, block=True)
cash_out = on_command("收签", priority=5, block=True)
give_up = on_command("弃签", priority=5, block=True)
start_ink_trace = on_command("墨宝寻踪", aliases={"墨宝"}, priority=5, block=True)
guess_ink_trace = on_command("寻踪", priority=5, block=True)
stargaze_ink_trace = on_command("观星", priority=5, block=True)
start_rps_duel = on_command("对饮猜拳", aliases={"酒令猜拳", "猜拳对盏"}, priority=5, block=True)
accept_rps_duel = on_command("接盏", aliases={"应战猜拳"}, priority=5, block=True)
decline_rps_duel = on_command("拒盏", priority=5, block=True)


@tavern.handle()
async def handle_tavern():
    await tavern.finish(_render_tavern_help())


@wine_balance.handle()
async def handle_wine_balance(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await wine_balance.finish(
            "（合上酒馆账本）酒钱按群里酒桌分别记账，请到群里查看。\n"
            "『酒旗要在人声里，独坐无桌不记杯。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    balance = get_wine_money(user_id, group_id)
    await wine_balance.finish(
        "🍶 太白酒馆·酒钱账 🍶\n"
        f"{'=' * 20}\n"
        "（本猫翻开酒馆小账）这壶里余多少，往后酒馆新局也照样能用。\n"
        f"当前酒钱：{balance}\n"
        f"{'=' * 20}\n"
        "『杯中余钱还可数，留待青灯再翻签。』"
    )


@exchange_wine.handle()
async def handle_exchange_wine(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await exchange_wine.finish(
            "（拎起酒壶又放下）添酒钱要在群里记账，请到群里来。\n"
            "『独坐无桌难斟账，众声入馆酒方明。』"
        )

    points_amount = parse_exchange_points(args.extract_plain_text())
    if points_amount is None:
        await exchange_wine.finish(
            "🍶 太白酒馆·添酒钱 🍶\n"
            f"{'=' * 20}\n"
            "用法：/兑换酒钱 积分数\n"
            "例：/兑换酒钱 5\n"
            f"{'=' * 20}\n"
            "『几分入柜添新酒，十钱一分落玉壶。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    result = exchange_points_to_wine(user_id, group_id, points_amount)
    if result["status"] == "insufficient_points":
        await exchange_wine.finish(
            "（本猫拨了拨账珠）这回积分不够添酒。\n"
            f"需用积分：{result['point_cost']}\n"
            f"当前积分：{result['points_balance']}\n"
            "『杯未满时先攒墨，待有余分再添壶。』"
        )

    if result["status"] != "ok":
        await exchange_wine.finish(
            "（柜上账珠忽然一顿）这笔酒钱暂未入壶，请稍后再试。\n"
            "『酒账偶逢灯影乱，重来一声便可清。』"
        )

    await exchange_wine.finish(
        "🍶 太白酒馆·添酒钱 🍶\n"
        f"{'=' * 20}\n"
        f"本次添酒：{result['point_cost']} 积分化作 {result['exchanged_wine']} 酒钱\n"
        f"当前酒钱：{result['wine_balance']}\n"
        f"{'=' * 20}\n"
        "『一分入柜添十盏，且把余香寄酒壶。』"
    )


@start_flip.handle()
async def handle_start_flip(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await start_flip.finish(
            "（拦在酒馆门口）灵签翻盘要在群里开桌，人声热闹才有酒气。\n"
            "『独斟不成翻盘局，入席方听签上风。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = _game_key(event)
    if game_key in active_games:
        game = active_games[game_key]
        await start_flip.finish(
            "（按住签筒）你桌上还有一局未了。\n"
            f"{'=' * 20}\n"
            f"{_format_board(game)}\n"
            f"{_status_line(game)}\n"
            f"{'=' * 20}\n"
            "继续：/翻签 位置｜收手：/收签｜退局：/弃签"
        )

    now = time.time()
    if game_key in cooldown and now - cooldown[game_key] < COOLDOWN_TIME:
        remaining = int(COOLDOWN_TIME - (now - cooldown[game_key]))
        await start_flip.finish(f"（给签筒压了压火）慢些，酒馆还要凉 {remaining} 秒。")

    start_args = parse_start_args(args.extract_plain_text())
    if start_args is None:
        await start_flip.finish(
            "🍶 太白酒馆·灵签翻盘 🍶\n"
            f"{'=' * 20}\n"
            "用法：/灵签翻盘 酒钱数 [凶签数]\n"
            "例：/灵签翻盘 10｜/灵签翻盘 10 3\n"
            f"{'=' * 20}\n"
            "不填凶签数为随机局；可指定 1-4 根凶签，越凶倍率越高。\n"
            "开桌后用 /翻签 位置 自选一支；可随时 /收签，/弃签 退 20%。\n"
            "『酒钱先落青瓷盏，五签才肯露锋芒。』"
        )

    wine_money = start_args["wine_money"]
    mode = start_args["mode"]
    wine_balance_value = get_wine_money(user_id, group_id)
    if wine_balance_value < wine_money:
        shortfall = wine_money - wine_balance_value
        await start_flip.finish(
            "（拨了拨酒馆账珠）这桌酒钱还差些。\n"
            f"入场需：{wine_money} 酒钱\n"
            f"现有酒钱：{wine_balance_value}\n"
            f"还差酒钱：{shortfall}（可先用 /兑换酒钱 {points_needed_for_wine(shortfall)} 添酒）\n"
            "『酒未入壶桌不开，先添一盏再翻签。』"
        )

    nickname = await get_nickname(bot, user_id, context="太白酒馆")
    bad_count = choose_bad_sign_count() if mode == RANDOM_MODE else int(mode)
    game = {
        "deck": new_sign_deck(bad_count),
        "revealed": [],
        "good_count": 0,
        "bad_count": bad_count,
        "mode": mode,
        "stake_wine": wine_money,
        "user_id": user_id,
        "group_id": group_id,
        "nickname": nickname,
        "started_at": now,
    }
    service = _round_service()
    round_id = new_round_id(FLIP_GAME_TYPE)
    game["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=FLIP_GAME_TYPE,
        mode="personal",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_WINE_MONEY,
        feature_key=FEATURE_KEY,
        payload=game,
        participants=[{"user_id": user_id, "amount": wine_money}],
    )
    charge = service.freeze_participant(round_id, user_id)
    if not charge["ok"]:
        service.refund_round(round_id, reason="insufficient_balance")
        await start_flip.finish(
            "（拨了拨酒馆账珠）这桌酒钱还差些。\n"
            f"入场需：{wine_money} 酒钱\n"
            f"现有酒钱：{charge['balance']}\n"
            "『酒未入壶桌不开，先添一盏再翻签。』"
        )
    active_games[game_key] = game
    cooldown[game_key] = now

    await start_flip.finish(
        "🍶 太白酒馆·灵签翻盘 🍶\n"
        f"{'=' * 20}\n"
        "（本猫把五支覆签一字排开）签面不见，胆色先见。\n"
        f"玩家：{nickname}\n"
        f"局型：{get_mode_label(mode)}\n"
        f"倍率：{mode_multiplier_text(mode)}\n"
        f"入场：{wine_money} 酒钱\n"
        f"酒钱余额：{charge['balance']}\n"
        f"{'=' * 20}\n"
        f"{_format_board(game)}\n"
        f"{_status_line(game)}\n"
        f"{'=' * 20}\n"
        "翻一支：/翻签 位置\n"
        "收手：/收签｜退局：/弃签"
    )


@reveal_sign.handle()
async def handle_reveal_sign(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await reveal_sign.finish("（收起签筒）翻签要在群里开桌。")

    game_key = _game_key(event)
    if game_key not in active_games:
        await reveal_sign.finish("（摊开空桌）你还没入太白酒馆。用 /灵签翻盘 酒钱数 开一局。")

    game = active_games[game_key]
    mode = game.get("mode", RANDOM_MODE)
    max_good_count = max_good_count_for_mode(mode, game.get("bad_count"))
    hidden_indexes = [index for index in range(SIGN_COUNT) if index not in set(game["revealed"])]
    position = parse_sign_position(args.extract_plain_text())
    if position is None:
        await reveal_sign.finish(
            "（敲敲签背）要点明翻哪一支。\n"
            f"{_format_board(game)}\n"
            "用法：/翻签 位置，例如 /翻签 3\n"
            "『签在桌前排成行，点哪一支才见章。』"
        )
    sign_index = position - 1
    if sign_index not in hidden_indexes:
        await reveal_sign.finish(
            "（按住那支签）这支已经翻过，换一支未开的。\n"
            f"{_format_board(game)}\n"
            "『旧签既露休重问，另拈新签看风声。』"
        )

    if not hidden_indexes:
        reward = calculate_reward_wine(game["stake_wine"], max_good_count, mode)
        service = _round_service()
        service.prepare_settlement(
            game["round_id"],
            result={"reason": "all_signs", "reward": reward, "game": game},
            payouts={game["user_id"]: reward},
        )
        service.settle_round(game["round_id"])
        active_games.pop(game_key, None)
        record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
        await reveal_sign.finish(
            "🍶 太白酒馆·满签结算 🍶\n"
            f"{'=' * 20}\n"
            f"{_format_board(game, reveal_all=True)}\n"
            f"{'=' * 20}\n"
            f"吉签皆过，最高倍率：{current_multiplier_text(max_good_count, mode)}\n"
            f"入账：{reward} 酒钱\n"
            f"酒钱余额：{record['wine_money']}\n"
            f"{'=' * 20}\n"
            "『五签齐照酒旗明，\n"
            "一夜风流满座惊。\n"
            "莫问彩头何处起，\n"
            "青灯偏爱稳中行。』"
        )

    game["revealed"].append(sign_index)
    sign = game["deck"][sign_index]
    if sign == "凶":
        service = _round_service()
        service.prepare_settlement(
            game["round_id"],
            result={"reason": "bad_sign", "position": position, "game": game},
            payouts={game["user_id"]: 0},
        )
        service.settle_round(game["round_id"])
        active_games.pop(game_key, None)
        balance = get_wine_money(game["user_id"], game["group_id"])
        await reveal_sign.finish(
            "🍶 太白酒馆·凶签落桌 🍶\n"
            f"{'=' * 20}\n"
            f"{_format_board(game, reveal_all=True)}\n"
            f"{'=' * 20}\n"
            "（签面一翻，墨色忽冷）凶签已出，本局酒钱清空。\n"
            f"本局：-{game['stake_wine']} 酒钱\n"
            f"酒钱余额：{balance}\n"
            f"{'=' * 20}\n"
            "『一签翻作冷风来，\n"
            "杯底浮光散不开。\n"
            "今日输赢都入梦，\n"
            "明朝再把酒旗抬。』"
        )

    game["good_count"] += 1
    good_count = game["good_count"]
    if good_count >= max_good_count:
        reward = calculate_reward_wine(game["stake_wine"], good_count, mode)
        service = _round_service()
        service.prepare_settlement(
            game["round_id"],
            result={"reason": "max_good_signs", "reward": reward, "game": game},
            payouts={game["user_id"]: reward},
        )
        service.settle_round(game["round_id"])
        active_games.pop(game_key, None)
        record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
        await reveal_sign.finish(
            "🍶 太白酒馆·满签结算 🍶\n"
            f"{'=' * 20}\n"
            f"{_format_board(game, reveal_all=True)}\n"
            f"{'=' * 20}\n"
            f"吉签皆过，最高倍率：{current_multiplier_text(good_count, mode)}\n"
            f"入账：{reward} 酒钱\n"
            f"酒钱余额：{record['wine_money']}\n"
            f"{'=' * 20}\n"
            "『五签齐照酒旗明，\n"
            "一夜风流满座惊。\n"
            "莫问彩头何处起，\n"
            "青灯偏爱稳中行。』"
        )

    _round_service().update_payload(game["round_id"], game)
    await reveal_sign.finish(
        "🍶 太白酒馆·灵签翻盘 🍶\n"
        f"{'=' * 20}\n"
        f"{_format_board(game)}\n"
        f"{'=' * 20}\n"
        "（签尖露出吉字）彩头涨了，心也该稳一稳。\n"
        f"{_status_line(game)}\n"
        f"{'=' * 20}\n"
        "继续：/翻签 位置｜收手：/收签｜退局：/弃签"
    )


@cash_out.handle()
async def handle_cash_out(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await cash_out.finish("（收起账本）收签要在群里结算。")

    game_key = _game_key(event)
    if game_key not in active_games:
        await cash_out.finish("（看了看空桌）眼下没有可收的灵签翻盘。")

    game = active_games[game_key]
    good_count = int(game.get("good_count", 0))
    if good_count <= 0:
        refund = calculate_refund_wine(game["stake_wine"])
        service = _round_service()
        service.prepare_settlement(
            game["round_id"],
            result={"reason": "cash_out_without_good", "refund": refund},
            payouts={game["user_id"]: refund},
        )
        service.settle_round(game["round_id"])
        active_games.pop(game_key, None)
        record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
        await cash_out.finish(
            "🍶 太白酒馆·空签收桌 🍶\n"
            f"{'=' * 20}\n"
            "（本猫把未翻的签压回筒中）尚未翻出吉字，只按弃签退些酒钱。\n"
            f"退还：{refund} 酒钱\n"
            f"酒钱余额：{record['wine_money']}\n"
            f"{'=' * 20}\n"
            "『未见吉光先收手，留杯明月待重来。』"
        )

    mode = game.get("mode", RANDOM_MODE)
    reward = calculate_reward_wine(game["stake_wine"], good_count, mode)
    service = _round_service()
    service.prepare_settlement(
        game["round_id"],
        result={"reason": "cash_out", "good_count": good_count, "reward": reward},
        payouts={game["user_id"]: reward},
    )
    service.settle_round(game["round_id"])
    active_games.pop(game_key, None)
    record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
    profit = reward - game["stake_wine"]
    profit_text = f"+{profit}" if profit >= 0 else str(profit)
    await cash_out.finish(
        "🍶 太白酒馆·收签结算 🍶\n"
        f"{'=' * 20}\n"
        f"{_format_board(game)}\n"
        f"{'=' * 20}\n"
        "（本猫替你把吉签压进账本）知进知退，也是酒馆上客。\n"
        f"吉签：{good_count} 支\n"
        f"倍率：{current_multiplier_text(good_count, mode)}\n"
        f"入账：{reward} 酒钱\n"
        f"本局盈亏：{profit_text} 酒钱\n"
        f"酒钱余额：{record['wine_money']}\n"
        f"{'=' * 20}\n"
        "『见好收来不算怯，\n"
        "酒香最怕一时贪。\n"
        "半桌风月归囊里，\n"
        "余签留待后来谈。』"
    )


@give_up.handle()
async def handle_give_up(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await give_up.finish("（合上酒馆门）弃签要在群里开桌。")

    game_key = _game_key(event)
    if game_key not in active_games:
        await give_up.finish("（看了看空桌）眼下没有可弃的灵签翻盘。")

    game = active_games[game_key]
    refund = calculate_refund_wine(game["stake_wine"])
    service = _round_service()
    service.prepare_settlement(
        game["round_id"],
        result={"reason": "give_up", "refund": refund},
        payouts={game["user_id"]: refund},
    )
    service.settle_round(game["round_id"])
    active_games.pop(game_key, None)
    record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
    await give_up.finish(
        "🍶 太白酒馆·弃签退桌 🍶\n"
        f"{'=' * 20}\n"
        "（本猫收起覆签）不翻也罢，留些酒钱给下一阵风。\n"
        f"退还：{refund} 酒钱\n"
        f"酒钱余额：{record['wine_money']}\n"
        f"{'=' * 20}\n"
        "『覆签未必都须开，\n"
        "留得三分可再来。\n"
        "今夜青灯先到此，\n"
        "明朝酒旗照楼台。』"
    )


@start_ink_trace.handle()
async def handle_start_ink_trace(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await start_ink_trace.finish(
            "（本猫把旧卷又塞回袖里）墨宝寻踪要在群里开卷，人声里才有诗脉。\n"
            "『独坐难寻旧墨痕，众声入卷月方明。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = _game_key(event)
    if game_key in active_ink_traces:
        game = active_ink_traces[game_key]
        await start_ink_trace.finish(
            "（本猫按住旧卷一角）你案上还有一枚墨宝未寻。\n"
            f"{'=' * 20}\n"
            f"意象：{_format_ink_trace_options(game)}\n"
            f"{'=' * 20}\n"
            "落子：/寻踪 意象｜观星：/观星"
        )

    wine_money = parse_wine_money(args.extract_plain_text())
    if wine_money is None:
        await start_ink_trace.finish(
            "🍶 太白酒馆·墨宝寻踪 🍶\n"
            f"{'=' * 20}\n"
            "用法：/墨宝寻踪 酒钱数\n"
            "例：/墨宝寻踪 20\n"
            f"{'=' * 20}\n"
            "本猫从酒、月、剑、花、云、舟里藏一枚墨宝；开卷后用 /寻踪 意象 作答。\n"
            "若心里没底，可用 /观星 排除一项空意象。\n"
            "『旧卷半开风带墨，且寻明月到杯中。』"
        )

    wine_balance_value = get_wine_money(user_id, group_id)
    if wine_balance_value < wine_money:
        shortfall = wine_money - wine_balance_value
        await start_ink_trace.finish(
            "（本猫摸了摸酒壶）这回寻墨的酒钱还差些。\n"
            f"入卷需：{wine_money} 酒钱\n"
            f"现有酒钱：{wine_balance_value}\n"
            f"还差酒钱：{shortfall}（可先用 /兑换酒钱 {points_needed_for_wine(shortfall)} 添酒）\n"
            "『壶中未满难开卷，先添一盏再寻诗。』"
        )

    nickname = await get_nickname(bot, user_id, context="太白酒馆")
    game = new_ink_trace_game(wine_money, user_id, group_id, nickname)
    service = _round_service()
    round_id = new_round_id(INK_GAME_TYPE)
    game["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=INK_GAME_TYPE,
        mode="personal",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_WINE_MONEY,
        feature_key=FEATURE_KEY,
        payload=game,
        participants=[{"user_id": user_id, "amount": wine_money}],
    )
    charge = service.freeze_participant(round_id, user_id)
    if not charge["ok"]:
        service.refund_round(round_id, reason="insufficient_balance")
        await start_ink_trace.finish(
            "（本猫摸了摸酒壶）这回寻墨的酒钱还差些。\n"
            f"入卷需：{wine_money} 酒钱\n"
            f"现有酒钱：{charge['balance']}\n"
            "『壶中未满难开卷，先添一盏再寻诗。』"
        )
    active_ink_traces[game_key] = game
    stargaze_cost = calculate_ink_trace_stargaze_cost(wine_money)

    await start_ink_trace.finish(
        "🍶 太白酒馆·墨宝寻踪 🍶\n"
        f"{'=' * 20}\n"
        "（本猫翻开一轴旧卷，又把酒壶往袖中一藏）墨痕已藏，且看谁能寻到诗眼。\n"
        f"玩家：{nickname}\n"
        f"入卷：{wine_money} 酒钱\n"
        f"酒钱余额：{charge['balance']}\n"
        f"{'=' * 20}\n"
        f"意象：{_format_ink_trace_options(game)}\n"
        f"{'=' * 20}\n"
        f"落子：/寻踪 意象｜观星：/观星（{stargaze_cost} 酒钱）"
    )


@stargaze_ink_trace.handle()
async def handle_stargaze_ink_trace(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await stargaze_ink_trace.finish("（收起星盘）观星要在群里开卷。")

    game_key = _game_key(event)
    if game_key not in active_ink_traces:
        await stargaze_ink_trace.finish("（抬头看了看空天）眼下没有可观的墨宝局。用 /墨宝寻踪 酒钱数 开一卷。")

    game = active_ink_traces[game_key]
    if game.get("stargazed"):
        await stargaze_ink_trace.finish(
            "（本猫把星盘一合）这一卷星光只借一次。\n"
            f"意象：{_format_ink_trace_options(game)}\n"
            "『天机不可重重问，留半分醉意给诗。』"
        )

    cost = calculate_ink_trace_stargaze_cost(game["stake_wine"])
    wine_balance_value = get_wine_money(game["user_id"], game["group_id"])
    if wine_balance_value < cost:
        await stargaze_ink_trace.finish(
            "（本猫摸了摸酒壶）观星还差一点酒钱。\n"
            f"观星需：{cost} 酒钱\n"
            f"现有酒钱：{wine_balance_value}\n"
            "『星盘也要沾杯气，添些酒钱再问天。』"
        )

    excluded = set(game.get("excluded", []))
    candidates = [
        option
        for option in game["options"]
        if option != game["treasure"] and option not in excluded
    ]
    revealed = random.choice(candidates) if candidates else None
    if revealed is None:
        await stargaze_ink_trace.finish(
            "（星光落到卷心）这一卷已无可排的空意象。\n"
            f"酒钱余额：{wine_balance_value}"
        )

    service = _round_service()
    participant_id = f"stargaze:{game['user_id']}"
    service.add_participant(
        game["round_id"],
        participant_id=participant_id,
        user_id=game["user_id"],
        amount=cost,
        metadata={"role": "auxiliary", "kind": "stargaze", "revealed": revealed},
    )
    charge = service.freeze_participant(game["round_id"], participant_id)
    if not charge["ok"]:
        await stargaze_ink_trace.finish(
            "（本猫摸了摸酒壶）观星还差一点酒钱。\n"
            f"观星需：{cost} 酒钱\n"
            f"现有酒钱：{charge['balance']}\n"
            "『星盘也要沾杯气，添些酒钱再问天。』"
        )
    game.setdefault("excluded", []).append(revealed)
    game["stargazed"] = True
    service.update_payload(game["round_id"], game)
    service.settle_participant(game["round_id"], participant_id)

    await stargaze_ink_trace.finish(
        "🍶 太白酒馆·墨宝观星 🍶\n"
        f"{'=' * 20}\n"
        "（本猫眯眼望星，袖中旧卷沙沙一响）这处没有墨宝。\n"
        f"排除：{revealed}\n"
        f"消耗：{cost} 酒钱\n"
        f"酒钱余额：{charge['balance']}\n"
        f"{'=' * 20}\n"
        f"意象：{_format_ink_trace_options(game)}\n"
        "落子：/寻踪 意象"
    )


@guess_ink_trace.handle()
async def handle_guess_ink_trace(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await guess_ink_trace.finish("（收起旧卷）寻踪要在群里开卷。")

    game_key = _game_key(event)
    if game_key not in active_ink_traces:
        await guess_ink_trace.finish("（翻了翻空卷）你还没开墨宝寻踪。用 /墨宝寻踪 酒钱数 开一卷。")

    game = active_ink_traces[game_key]
    guess = parse_ink_trace_guess(args.extract_plain_text())
    if guess is None or guess not in game["options"]:
        await guess_ink_trace.finish(
            "（本猫敲敲卷轴）要从这一卷意象里择一个。\n"
            f"意象：{_format_ink_trace_options(game)}\n"
            "用法：/寻踪 意象，例如 /寻踪 月\n"
            "『诗眼藏在卷中处，须点其名才见真。』"
        )
    if guess in set(game.get("excluded", [])):
        await guess_ink_trace.finish(
            "（本猫摇摇酒壶）这处已被星光照空，换个未排除的意象。\n"
            f"意象：{_format_ink_trace_options(game)}\n"
            "『空处不须重下笔，另寻一字问青天。』"
        )

    if guess == game["treasure"]:
        reward = calculate_ink_trace_reward_wine(game["stake_wine"], game["treasure"])
        service = _round_service()
        service.prepare_settlement(
            game["round_id"],
            result={"reason": "found", "guess": guess, "reward": reward},
            payouts={game["user_id"]: reward},
        )
        service.settle_round(game["round_id"])
        active_ink_traces.pop(game_key, None)
        record = {"wine_money": get_wine_money(game["user_id"], game["group_id"])}
        profit = reward - game["stake_wine"]
        await guess_ink_trace.finish(
            "🍶 太白酒馆·墨宝寻踪 🍶\n"
            f"{'=' * 20}\n"
            "（旧卷忽然透出一线墨光）正是此处，墨宝入手。\n"
            f"墨宝：{get_ink_trace_treasure_name(game['treasure'])}（{game['treasure']}）\n"
            f"入账：{reward} 酒钱\n"
            f"本局盈亏：+{profit} 酒钱\n"
            f"酒钱余额：{record['wine_money']}\n"
            f"{'=' * 20}\n"
            "『旧卷寻来一点真，\n"
            "杯中明月照诗痕。\n"
            "莫言墨宝藏无处，\n"
            "醉里青天也有门。』"
        )

    service = _round_service()
    service.prepare_settlement(
        game["round_id"],
        result={"reason": "missed", "guess": guess, "treasure": game["treasure"]},
        payouts={game["user_id"]: 0},
    )
    service.settle_round(game["round_id"])
    active_ink_traces.pop(game_key, None)
    balance = get_wine_money(game["user_id"], game["group_id"])
    await guess_ink_trace.finish(
        "🍶 太白酒馆·墨宝寻踪 🍶\n"
        f"{'=' * 20}\n"
        "（本猫抖了抖旧卷，墨光从别处一闪而过）这一笔寻偏了。\n"
        f"你寻：{guess}\n"
        f"墨宝：{get_ink_trace_treasure_name(game['treasure'])}（{game['treasure']}）\n"
        f"本局：-{game['stake_wine']} 酒钱\n"
        f"酒钱余额：{balance}\n"
        f"{'=' * 20}\n"
        "『月下寻诗误入云，\n"
        "酒壶轻响笑前因。\n"
        "输赢且作风中过，\n"
        "明日重翻旧卷尘。』"
    )


@start_rps_duel.handle()
async def handle_start_rps_duel(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await start_rps_duel.finish(
            "（本猫把两只酒盏收回袖中）对饮猜拳要在群里邀友开桌。\n"
            "『独坐难成双拳局，且向人声借一杯。』"
        )

    parsed = parse_rps_challenge_args(args)
    if parsed is None:
        await start_rps_duel.finish(
            "🍶 太白酒馆·对饮猜拳 🍶\n"
            f"{'=' * 20}\n"
            "用法：/对饮猜拳 @群友 酒钱数\n"
            "例：/对饮猜拳 @群友 20\n"
            f"{'=' * 20}\n"
            "对方接盏后，双方各封同额酒钱；本猫依次发送两枚 QQ 原生猜拳，胜者收双份，平局各归原额。\n"
            "『先邀知己临风坐，再看双拳落酒台。』"
        )

    challenger_id = event.get_user_id()
    target_id = parsed["target_id"]
    stake_wine = parsed["stake_wine"]
    if target_id == challenger_id:
        await start_rps_duel.finish(
            "（本猫按住你左右互碰的两只手）自己不能向自己邀拳。\n"
            "『一人纵有双拳在，也少同杯对饮声。』"
        )
    if target_id == str(event.self_id):
        await start_rps_duel.finish(
            "（本猫晃晃酒壶）这局要请群友对饮，本猫只掌拳、记账，不亲自下场。\n"
            "『酒旗今日司公断，且请双客各登台。』"
        )

    group_id = str(event.group_id)
    challenger_balance = get_wine_money(challenger_id, group_id)
    if challenger_balance < stake_wine:
        shortfall = stake_wine - challenger_balance
        await start_rps_duel.finish(
            "（本猫拨了拨邀拳酒盏）你的酒钱还不够摆下这一桌。\n"
            f"每人需封：{stake_wine} 酒钱\n"
            f"你的酒钱：{challenger_balance}\n"
            f"还差酒钱：{shortfall}（可先用 /兑换酒钱 {points_needed_for_wine(shortfall)} 添酒）\n"
            "『杯中未满休催拳，添得新醅再请君。』"
        )

    challenger_nickname = await get_nickname(bot, challenger_id, context="太白酒馆对饮猜拳")
    target_nickname = await get_nickname(bot, target_id, context="太白酒馆对饮猜拳")
    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        if group_id in active_rps_duels:
            await start_rps_duel.finish(
                "（本猫指指桌上尚未散去的拳影）本桌已有一局对饮猜拳正在验拳，请稍候。"
            )

        existing = pending_rps_challenges.get(group_id)
        if existing is not None and _challenge_expired(existing):
            pending_rps_challenges.pop(group_id, None)
            existing = None
        if existing is not None:
            await start_rps_duel.finish(
                "（本猫按住新端来的酒盏）本桌已有一封邀拳尚待回应，可先用 /接盏 或 /拒盏 了结。"
            )

        challenge_id = new_round_id("tavern_rps_challenge")
        challenge = {
            "challenge_id": challenge_id,
            "group_id": group_id,
            "challenger_id": challenger_id,
            "challenger_nickname": challenger_nickname,
            "target_id": target_id,
            "target_nickname": target_nickname,
            "stake_wine": stake_wine,
            "created_at": time.time(),
            "expires_at": time.time() + RPS_CHALLENGE_TIMEOUT_SECONDS,
        }
        pending_rps_challenges[group_id] = challenge
        asyncio.create_task(_expire_pending_rps_challenge(bot, group_id, challenge_id))

    await start_rps_duel.finish(
        "🍶 太白酒馆·对饮猜拳邀盏 🍶\n"
        f"{'=' * 20}\n"
        f"邀拳：{challenger_nickname}\n"
        f"受邀：{target_nickname}\n"
        f"每人酒钱：{stake_wine}\n"
        f"{'=' * 20}\n"
        f"{target_nickname} 请在 {RPS_CHALLENGE_TIMEOUT_SECONDS} 秒内用 /接盏 应战，或用 /拒盏 婉拒。\n"
        "接盏前不扣酒钱；接盏后由本猫发送两枚 QQ 原生猜拳并据实结算。\n"
        "『两盏先陈青案上，等君一诺起拳风。』"
    )


@accept_rps_duel.handle()
async def handle_accept_rps_duel(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await accept_rps_duel.finish("（本猫合上空账）接盏要回到发出邀拳的群里。")

    group_id = str(event.group_id)
    user_id = event.get_user_id()
    service = _round_service()
    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        challenge = pending_rps_challenges.get(group_id)
        if challenge is None:
            await accept_rps_duel.finish(
                "（本猫看看空桌）眼下没有待接的猜拳酒盏，可用 /对饮猜拳 @群友 酒钱数 发起。"
            )
        if _challenge_expired(challenge):
            pending_rps_challenges.pop(group_id, None)
            await accept_rps_duel.finish(
                "（本猫摸摸已经凉下来的酒盏）这封邀拳已过时，尚未扣取任何酒钱，请重新邀盏。"
            )
        if user_id != challenge["target_id"]:
            await accept_rps_duel.finish(
                f"（本猫把酒盏转回原位）这一盏是留给 {challenge['target_nickname']} 的，旁人不能代接。"
            )
        if group_id in active_rps_duels:
            await accept_rps_duel.finish("（本猫按住账页）这一桌已经开拳，莫重复接盏。")

        pending_rps_challenges.pop(group_id, None)
        try:
            result = create_rps_duel_round(challenge, service=service)
        except Exception as exc:
            logger.exception(f"创建对饮猜拳付费回合失败 group_id={group_id}: {exc}")
            await accept_rps_duel.finish(
                "（柜上两枚账珠忽然相撞）这局暂未开成，若有酒钱落账也会原路归壶，请稍后再邀。\n"
                "『拳未登台账先止，待灯重稳再开杯。』"
            )

        if result["status"] != "ok":
            short_name = challenge[
                "challenger_nickname"
                if result["status"] == "challenger_insufficient_wine"
                else "target_nickname"
            ]
            await accept_rps_duel.finish(
                "（本猫把两只尚未开拳的酒盏一并退回）有人酒钱不足，本局未成，双方都未损酒钱。\n"
                f"不足者：{short_name}\n"
                f"每人需封：{challenge['stake_wine']} 酒钱\n"
                f"当前酒钱：{result['balance']}\n"
                "『一盏未盈双客止，添酒之后再论拳。』"
            )

    await _settle_rps_duel(bot, group_id, service=service)


@decline_rps_duel.handle()
async def handle_decline_rps_duel(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await decline_rps_duel.finish("（本猫收起空盏）拒盏要回到发出邀拳的群里。")

    group_id = str(event.group_id)
    user_id = event.get_user_id()
    lock = rps_duel_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        challenge = pending_rps_challenges.get(group_id)
        if challenge is None:
            if group_id in active_rps_duels:
                await decline_rps_duel.finish("（本猫按住已落账的酒盏）双方既已接盏开拳，便不能再以拒盏撤局。")
            await decline_rps_duel.finish("（本猫看看空桌）眼下没有待回的猜拳酒盏。")
        if user_id not in {challenge["challenger_id"], challenge["target_id"]}:
            await decline_rps_duel.finish("（本猫轻敲桌沿）这封邀拳与你无关，不可替人收盏。")
        pending_rps_challenges.pop(group_id, None)

    await decline_rps_duel.finish(
        "（本猫把两只尚未斟满的酒盏收回柜上）此番邀拳作罢，尚未扣取任何酒钱。\n"
        "『今日无拳杯仍暖，改时相见再同斟。』"
    )
