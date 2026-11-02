from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="legacy_scratch",
    name="刮刮挑战",
    default_enabled=False,
    scope="group",
    permission_level=4,
    data_files=("data/paid_rounds.json", "data/points.json"),
    privacy_level="personal",
    backup_policy="standard",
)

import random
import time

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.rule import Rule

from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.accounting import ASSET_POINTS, get_points
from mybot.common.paid_rounds import (
    PaidRoundService,
    new_round_id,
    register_recovery_adapter,
)
from mybot.plugins.rate_limit import check_game_limit, get_limit_message


logger = get_plugin_logger(__name__)
FEATURE_KEY = "legacy_scratch"
GAME_TYPE = "scratch"
COOLDOWN_TIME = 3
CARD_COUNT = 9
PICK_COUNT = 3

HELP_ITEMS = (
    HelpItem("小游戏", "/刮刮挑战 级别 - 刮刮挑战", 70),
)
COMMAND_ALIASES = (
    "刮刮挑战",
    "刮刮乐",
    "刮刮",
    "刮开",
    "刮牌",
    "放弃刮刮",
)


async def _feature_enabled(event: MessageEvent) -> bool:
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    return is_feature_enabled(FEATURE_KEY, group_id)


FEATURE_RULE = Rule(_feature_enabled)

active_games: dict[str, dict] = {}
cooldown: dict[str, float] = {}


def _round_service() -> PaidRoundService:
    return PaidRoundService()


def _restore_round(round_record: dict, service: PaidRoundService) -> None:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    active_games[f"{round_record['group_id']}_{round_record['creator_id']}"] = game


def _round_is_loaded(round_record: dict) -> bool:
    game_key = f"{round_record['group_id']}_{round_record['creator_id']}"
    return active_games.get(game_key, {}).get("round_id") == round_record["round_id"]


def _discard_round(round_record: dict, service: PaidRoundService) -> None:
    game_key = f"{round_record['group_id']}_{round_record['creator_id']}"
    if active_games.get(game_key, {}).get("round_id") == round_record["round_id"]:
        active_games.pop(game_key, None)


register_recovery_adapter(
    GAME_TYPE,
    restore=_restore_round,
    is_loaded=_round_is_loaded,
    discard=_discard_round,
)

SYMBOL_DISPLAY = {
    "空牌": "□",
    "铜钱": "🪙",
    "酒壶": "🍶",
    "玉佩": "💠",
    "月魄": "🌙",
    "太白令": "📜",
}

LEVEL_CONFIGS = {
    1: {
        "cost": 20,
        "weights": {"空牌": 55, "铜钱": 28, "酒壶": 12, "玉佩": 4, "月魄": 0.8, "太白令": 0.2},
        "scores": {"空牌": 0, "铜钱": 5, "酒壶": 15, "玉佩": 45, "月魄": 120, "太白令": 300},
    },
    2: {
        "cost": 50,
        "weights": {"空牌": 48, "铜钱": 28, "酒壶": 15, "玉佩": 6, "月魄": 2, "太白令": 1},
        "scores": {"空牌": 0, "铜钱": 8, "酒壶": 20, "玉佩": 50, "月魄": 140, "太白令": 480},
    },
    3: {
        "cost": 100,
        "weights": {"空牌": 42, "铜钱": 26, "酒壶": 18, "玉佩": 9, "月魄": 3.5, "太白令": 1.5},
        "scores": {"空牌": 0, "铜钱": 10, "酒壶": 32, "玉佩": 85, "月魄": 250, "太白令": 550},
    },
}

START_MESSAGES = [
    "（抖开旧木匣）九张背牌排好了，挑三张，看看今日手气。",
    "（推墨镜）刮刮纸一铺，月光都躲在背面，敢不敢挑？",
    "（晃酒壶）三爪定乾坤，别问本猫哪张好，问就是缘分。",
]

WIN_MESSAGES = [
    "（拍桌）好手气！这三张刮得有点东西。",
    "（举杯）旧纸一翻，墨钱自来，阁下今日有光。",
    "（点头）这手不差，本猫给你记一笔彩头。",
]

LOSE_MESSAGES = [
    "（收起碎纸）没刮出名堂，且当给旧匣添了点酒钱。",
    "（递茶）这三张不认人，明日再来换个手势。",
    "（摇头）纸背无月，手边无财，先稳一稳。",
]

NO_POINTS_MESSAGES = [
    "（合上旧匣）你只有 {points} 积分，墨钱不够，先去签到攒点吧。",
    "（按住刮刀）囊中羞涩也莫急，先攒些积分再来翻牌。",
]


def _parse_level(text: str) -> int | None:
    normalized = text.strip().replace("级", "").replace("档", "")
    aliases = {"一": 1, "二": 2, "三": 3}
    if normalized in aliases:
        return aliases[normalized]
    if normalized.isdigit():
        level = int(normalized)
        if level in LEVEL_CONFIGS:
            return level
    return None


def _new_deck(level: int) -> list[dict[str, str]]:
    config = LEVEL_CONFIGS[level]
    names = list(config["weights"])
    weights = [config["weights"][name] for name in names]
    picks = random.choices(names, weights=weights, k=CARD_COUNT)
    return [{"name": name, "display": SYMBOL_DISPLAY[name]} for name in picks]


def _format_hidden_board() -> str:
    rows = []
    for start in range(0, CARD_COUNT, 3):
        rows.append("  ".join(f"{index:02d}.▣" for index in range(start + 1, start + 4)))
    return "\n".join(rows)


def _format_revealed_board(deck: list[dict[str, str]], selected: set[int]) -> str:
    rows = []
    for start in range(0, CARD_COUNT, 3):
        cells = []
        for index in range(start, start + 3):
            card = deck[index]
            face = card["display"] if index in selected else "▣"
            cells.append(f"{index + 1:02d}.{face}")
        rows.append("  ".join(cells))
    return "\n".join(rows)


def _parse_positions(text: str) -> list[int] | None:
    parts = text.replace("，", " ").replace(",", " ").split()
    if len(parts) != PICK_COUNT:
        return None

    positions = []
    for part in parts:
        if not part.isdigit():
            return None
        position = int(part)
        if position < 1 or position > CARD_COUNT or position in positions:
            return None
        positions.append(position)
    return positions


def calculate_reward(cards: list[dict[str, str]], level: int) -> tuple[int, str]:
    scores = LEVEL_CONFIGS[level]["scores"]
    parts = [f"{card['display']}{card['name']}+{scores[card['name']]}" for card in cards]
    reward = sum(scores[card["name"]] for card in cards)
    return reward, "，".join(parts)


def expected_reward(level: int) -> float:
    config = LEVEL_CONFIGS[level]
    total_weight = sum(config["weights"].values())
    expected_card = sum(
        config["weights"][name] / total_weight * config["scores"][name]
        for name in config["weights"]
    )
    return expected_card * PICK_COUNT


def _game_key(event: GroupMessageEvent) -> str:
    return f"{event.group_id}_{event.get_user_id()}"


scratch = on_command("刮刮挑战", aliases={"刮刮乐", "刮刮"}, rule=FEATURE_RULE, priority=5, block=True)


@scratch.handle()
async def handle_scratch(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await scratch.finish("（摇头）刮刮挑战要在群里翻才热闹嘛~")

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = _game_key(event)

    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"刮刮挑战获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id

    if game_key in active_games:
        await scratch.finish(
            "（敲敲旧匣）你还有一局刮刮挑战没刮完。\n"
            f"{'=' * 20}\n"
            f"{_format_hidden_board()}\n"
            f"{'=' * 20}\n"
            "用法：/刮开 1 5 9"
        )

    now = time.time()
    if game_key in cooldown and now - cooldown[game_key] < COOLDOWN_TIME:
        remaining = int(COOLDOWN_TIME - (now - cooldown[game_key]))
        await scratch.finish(f"（按住刮刀）慢些，旧匣还要凉 {remaining} 秒。")

    level_text = args.extract_plain_text().strip()
    if not level_text:
        await scratch.finish(
            f"🎴 李太白给·刮刮挑战 🎴\n"
            f"{'=' * 20}\n"
            "用法：/刮刮挑战 级别\n"
            "级别：1级20积分｜2级50积分｜3级100积分\n"
            "开局后用：/刮开 位置1 位置2 位置3\n"
            f"{'=' * 20}\n"
            "本猫会摆出九张背面牌，你挑三张刮开。\n"
            "每张图案各有分值，三张所得相加结算。\n"
            "级别越高，贵重图案越容易露面，入场墨钱也越重。\n"
            f"{'=' * 20}\n"
            "图案：空牌、铜钱、酒壶、玉佩、月魄、太白令\n"
            f"{'=' * 20}\n"
            "『九纸藏风月，三刮见浮沉。\n"
            "手稳休贪快，得失且听吟。』"
        )

    level = _parse_level(level_text)
    if level is None:
        await scratch.finish("（敲敲旧匣）级别只收 1、2、3。例：/刮刮挑战 2")

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await scratch.finish(get_limit_message(result))

    bet = LEVEL_CONFIGS[level]["cost"]
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet:
        await scratch.finish(random.choice(NO_POINTS_MESSAGES).format(points=points_info["current"]))

    game = {
        "deck": _new_deck(level),
        "bet": bet,
        "level": level,
        "nickname": nickname,
        "group_id": group_id,
        "user_id": user_id,
    }
    service = _round_service()
    round_id = new_round_id(GAME_TYPE)
    game["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=GAME_TYPE,
        mode="personal",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_POINTS,
        feature_key=FEATURE_KEY,
        payload=game,
        participants=[{"user_id": user_id, "amount": bet}],
    )
    charge = service.freeze_participant(round_id, user_id)
    if not charge["ok"]:
        service.refund_round(round_id, reason="insufficient_balance")
        await scratch.finish(random.choice(NO_POINTS_MESSAGES).format(points=charge["balance"]))
    cooldown[game_key] = now
    active_games[game_key] = game

    await scratch.finish(
        f"🎴 李太白给·刮刮挑战 🎴\n"
        f"{'=' * 20}\n"
        f"{random.choice(START_MESSAGES)}\n"
        f"玩家：{nickname}\n"
        f"级别：{level}级\n"
        f"入场：{bet} 积分\n"
        f"{'=' * 20}\n"
        f"{_format_hidden_board()}\n"
        f"{'=' * 20}\n"
        "挑三张：/刮开 1 5 9\n"
        "放弃本局：/放弃刮刮"
    )


reveal = on_command("刮开", aliases={"刮牌"}, rule=FEATURE_RULE, priority=5, block=True)


@reveal.handle()
async def handle_reveal(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await reveal.finish("（摇头）要在群里刮哦~")

    game_key = _game_key(event)
    if game_key not in active_games:
        await reveal.finish("（摊手）你还没开刮刮挑战呢。输入 /刮刮挑战 级别 试试。")

    positions = _parse_positions(args.extract_plain_text().strip())
    if not positions:
        await reveal.finish("（敲敲牌背）要选三张不同的牌，格式：/刮开 1 5 9")

    game = active_games[game_key]
    selected_indexes = {position - 1 for position in positions}
    selected_cards = [game["deck"][position - 1] for position in positions]
    reward, reason = calculate_reward(selected_cards, game["level"])
    service = _round_service()
    service.prepare_settlement(
        game["round_id"],
        result={
            "reason": "revealed",
            "positions": positions,
            "selected_cards": selected_cards,
            "reward": reward,
        },
        payouts={game["user_id"]: reward},
    )
    service.settle_round(game["round_id"])
    active_games.pop(game_key, None)

    profit = reward - game["bet"]
    profit_text = f"+{profit}" if profit > 0 else str(profit)
    selected_text = " ".join(card["display"] for card in selected_cards)
    comment = random.choice(WIN_MESSAGES if reward > game["bet"] else LOSE_MESSAGES)
    new_points = get_points(game["user_id"], game["group_id"])

    poem = (
        "三纸翻开照旧尘，\n"
        "一时得失莫伤神。\n"
        "若问彩头何处去，\n"
        "明朝还看手中春。"
    )

    await reveal.finish(
        f"🎴 李太白给·刮刮挑战 🎴\n"
        f"{'=' * 20}\n"
        f"{_format_revealed_board(game['deck'], selected_indexes)}\n"
        f"{'=' * 20}\n"
        f"刮开：{selected_text}\n"
        f"计分：{reason}\n"
        f"合计：{reward} 积分\n"
        f"{'=' * 20}\n"
        f"本局：{profit_text} 积分\n"
        f"余额：{new_points['current']} 积分\n"
        f"{'=' * 20}\n"
        f"{comment}\n"
        f"{'=' * 20}\n"
        f"『{poem}』"
    )


give_up = on_command("放弃刮刮", aliases={"取消刮刮"}, rule=FEATURE_RULE, priority=5, block=True)


@give_up.handle()
async def handle_give_up(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await give_up.finish("（摇头）要在群里操作哦~")

    game_key = _game_key(event)
    if game_key not in active_games:
        await give_up.finish("（摊手）眼下没有可放弃的刮刮挑战。")

    game = active_games[game_key]
    refund = game["bet"] // 2
    service = _round_service()
    service.prepare_settlement(
        game["round_id"],
        result={"reason": "give_up", "refund": refund},
        payouts={game["user_id"]: refund},
    )
    service.settle_round(game["round_id"])
    active_games.pop(game_key, None)

    new_points = get_points(game["user_id"], game["group_id"])
    await give_up.finish(
        f"🎴 刮刮挑战已收起\n"
        f"{'=' * 20}\n"
        "（合上旧匣）知进退，也算好手。\n"
        f"退还：{refund} 积分\n"
        f"余额：{new_points['current']} 积分\n"
        f"{'=' * 20}\n"
        "『纸背风波未必开，\n"
        "留些墨钱待后来。\n"
        "今朝收手非怯意，\n"
        "明月仍照旧楼台。』"
    )
