import random
import time
from math import ceil, comb
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.help_registry import HelpItem
from mybot.common.json_store import load_json, mutate_json
from mybot.common.logger import get_plugin_logger
from mybot.common.user_utils import get_nickname
from mybot.plugins.points import get_points, refund_points, spend_points


logger = get_plugin_logger(__name__)

POINT_TO_WINE = 10
SIGN_COUNT = 5
INK_TRACE_IMAGES = ("酒", "月", "剑", "花", "云", "舟")
INK_TRACE_OPTION_COUNTS = (3, 4)
INK_TRACE_REWARD_TENTHS_BY_IMAGE = {
    "酒": 18,
    "月": 20,
    "剑": 22,
    "舟": 24,
    "云": 26,
    "花": 30,
}
INK_TRACE_TREASURE_WEIGHTS = {
    "酒": 18,
    "月": 16,
    "剑": 14,
    "舟": 12,
    "云": 10,
    "花": 7,
}
INK_TRACE_TREASURE_NAMES = {
    "酒": "醉仙残盏",
    "月": "水月银笺",
    "剑": "青锋诗骨",
    "花": "绯落小印",
    "云": "云帆墨契",
    "舟": "夜泊孤篆",
}
INK_TRACE_STARGAZE_TENTHS = 6
BAD_SIGN_ZERO_WEIGHT = 10
BAD_SIGN_ONE_WEIGHT = 35
BAD_SIGN_TWO_WEIGHT = 55
REFUND_TENTHS = 2
COOLDOWN_TIME = 3
RANDOM_MODE = "random"
FIXED_BAD_SIGN_COUNTS = (1, 2, 3, 4)
MODE_MULTIPLIER_TENTHS = {
    RANDOM_MODE: (11, 15, 23, 38, 75),
    1: (10, 12.5, 17, 25),
    2: (13, 20, 60),
    3: (20, 80),
    4: (40,),
}
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "taibai_tavern.json"
DEFAULT_TAVERN_DATA = {"accounts": {}}
BAD_SIGN_PRIOR_WEIGHTS = {
    0: BAD_SIGN_ZERO_WEIGHT,
    1: BAD_SIGN_ONE_WEIGHT,
    2: BAD_SIGN_TWO_WEIGHT,
}

HELP_ITEMS = (
    HelpItem("太白酒馆", "/太白酒馆 - 酒馆总览与酒钱规则", 10),
    HelpItem("太白酒馆", "/酒钱 - 查看酒馆酒钱", 20),
    HelpItem("太白酒馆", "/兑换酒钱 积分数 - 添酒钱", 30),
    HelpItem("太白酒馆", "/灵签翻盘 酒钱数 - 酒馆灵签局", 40),
    HelpItem("太白酒馆", "/墨宝寻踪 酒钱数 - 寻诗猜墨宝", 50),
)
COMMAND_ALIASES = (
    "太白酒馆",
    "酒钱",
    "我的酒钱",
    "酒钱余额",
    "兑换酒钱",
    "灵签翻盘",
    "翻签",
    "收签",
    "弃签",
    "墨宝寻踪",
    "寻踪",
    "观星",
)

active_games: dict[str, dict] = {}
active_ink_traces: dict[str, dict] = {}
cooldown: dict[str, float] = {}


def _game_key(event: GroupMessageEvent) -> str:
    return f"{event.group_id}_{event.get_user_id()}"


def parse_wine_money(text: str) -> int | None:
    normalized = text.strip().replace("酒钱", "").replace("枚", "").replace("文", "").strip()
    if not normalized.isdigit():
        return None
    amount = int(normalized)
    if amount <= 0:
        return None
    return amount


def parse_start_args(text: str) -> dict | None:
    parts = text.replace("，", " ").replace(",", " ").split()
    if not parts:
        return None
    if len(parts) > 2:
        return None

    wine_money = parse_wine_money(parts[0])
    if wine_money is None:
        return None

    mode: str | int = RANDOM_MODE
    if len(parts) >= 2:
        mode_text = parts[1].strip().replace("凶签", "").replace("凶", "")
        aliases = {"一": 1, "二": 2, "三": 3, "四": 4}
        if mode_text in {"随机", "随", "random"}:
            mode = RANDOM_MODE
        elif mode_text in aliases:
            mode = aliases[mode_text]
        elif mode_text.isdigit() and int(mode_text) in FIXED_BAD_SIGN_COUNTS:
            mode = int(mode_text)
        else:
            return None

    return {"wine_money": wine_money, "mode": mode}


def parse_sign_position(text: str) -> int | None:
    normalized = text.strip().replace("号", "").replace("签", "")
    aliases = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    if normalized in aliases:
        return aliases[normalized]
    if not normalized.isdigit():
        return None
    position = int(normalized)
    if position < 1 or position > SIGN_COUNT:
        return None
    return position


def parse_ink_trace_guess(text: str) -> str | None:
    normalized = text.strip().replace("墨宝", "").replace("意象", "").strip()
    if normalized in INK_TRACE_IMAGES:
        return normalized
    return None


def points_to_wine(points_amount: int) -> int:
    return points_amount * POINT_TO_WINE


def points_needed_for_wine(wine_money: int) -> int:
    return ceil(wine_money / POINT_TO_WINE)


def parse_exchange_points(text: str) -> int | None:
    normalized = text.strip().replace("积分", "").replace("分", "").strip()
    if not normalized.isdigit():
        return None
    amount = int(normalized)
    if amount <= 0:
        return None
    return amount


def _account_key(user_id: str, group_id: str) -> str:
    return f"{group_id}_{user_id}"


def _new_account_record(user_id: str, group_id: str) -> dict:
    return {"wine_money": 0, "user_id": user_id, "group_id": group_id}


def get_wine_money(user_id: str, group_id: str) -> int:
    key = _account_key(user_id, group_id)
    data = load_json(DATA_FILE, DEFAULT_TAVERN_DATA)
    record = data.get("accounts", {}).get(key, {})
    try:
        return max(int(record.get("wine_money", 0)), 0)
    except (TypeError, ValueError):
        return 0


def add_wine_money(user_id: str, group_id: str, amount: int) -> dict:
    key = _account_key(user_id, group_id)

    def mutator(data: dict) -> dict:
        accounts = data.setdefault("accounts", {})
        record = accounts.setdefault(key, _new_account_record(user_id, group_id))
        record["wine_money"] = max(int(record.get("wine_money", 0)), 0) + amount
        return dict(record)

    return mutate_json(DATA_FILE, DEFAULT_TAVERN_DATA, mutator)


def spend_wine_money(user_id: str, group_id: str, amount: int) -> dict:
    key = _account_key(user_id, group_id)

    def mutator(data: dict) -> dict:
        accounts = data.setdefault("accounts", {})
        record = accounts.setdefault(key, _new_account_record(user_id, group_id))
        current = max(int(record.get("wine_money", 0)), 0)
        if current < amount:
            return {"ok": False, "balance": current, "record": dict(record)}
        record["wine_money"] = current - amount
        return {"ok": True, "balance": record["wine_money"], "record": dict(record)}

    return mutate_json(DATA_FILE, DEFAULT_TAVERN_DATA, mutator)


def exchange_points_to_wine(user_id: str, group_id: str, points_amount: int) -> dict:
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
        record = add_wine_money(user_id, group_id, wine_amount)
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


def prepare_wine_stake(user_id: str, group_id: str, stake_wine: int) -> dict:
    spend_result = spend_wine_money(user_id, group_id, stake_wine)
    if spend_result["ok"]:
        return {"status": "ok", "wine_balance": spend_result["balance"], "record": spend_result["record"]}

    shortfall = stake_wine - spend_result["balance"]
    return {
        "status": "insufficient_wine",
        "wine_balance": spend_result["balance"],
        "shortfall": shortfall,
        "point_cost": points_needed_for_wine(shortfall),
    }


def choose_bad_sign_count() -> int:
    return random.choices(
        (0, 1, 2),
        weights=(BAD_SIGN_ZERO_WEIGHT, BAD_SIGN_ONE_WEIGHT, BAD_SIGN_TWO_WEIGHT),
        k=1,
    )[0]


def new_sign_deck(bad_count: int | None = None) -> list[str]:
    bad_total = bad_count if bad_count in range(0, SIGN_COUNT) else choose_bad_sign_count()
    deck = ["凶"] * bad_total + ["吉"] * (SIGN_COUNT - bad_total)
    random.shuffle(deck)
    return deck


def get_mode_multipliers(mode: str | int = RANDOM_MODE) -> tuple[float, ...]:
    return MODE_MULTIPLIER_TENTHS.get(mode, MODE_MULTIPLIER_TENTHS[RANDOM_MODE])


def get_mode_bad_weights(mode: str | int = RANDOM_MODE) -> dict[int, int]:
    if isinstance(mode, int) and mode in FIXED_BAD_SIGN_COUNTS:
        return {mode: 1}
    return BAD_SIGN_PRIOR_WEIGHTS


def get_mode_label(mode: str | int = RANDOM_MODE) -> str:
    if mode == RANDOM_MODE:
        return "随机凶签"
    return f"{mode} 凶签"


def max_good_count_for_mode(mode: str | int = RANDOM_MODE, bad_count: int | None = None) -> int:
    if isinstance(bad_count, int):
        return SIGN_COUNT - bad_count
    if isinstance(mode, int) and mode in FIXED_BAD_SIGN_COUNTS:
        return SIGN_COUNT - mode
    return SIGN_COUNT


def calculate_reward_wine(stake_wine: int, good_count: int, mode: str | int = RANDOM_MODE) -> int:
    if good_count <= 0:
        return 0
    multipliers = get_mode_multipliers(mode)
    capped_count = min(good_count, len(multipliers))
    return int(round(stake_wine * (multipliers[capped_count - 1] / 10), 8))


def calculate_refund_wine(stake_wine: int) -> int:
    return stake_wine * REFUND_TENTHS // 10


def get_ink_trace_reward_tenths(image: str) -> int:
    return INK_TRACE_REWARD_TENTHS_BY_IMAGE.get(image, INK_TRACE_REWARD_TENTHS_BY_IMAGE["月"])


def get_ink_trace_treasure_name(image: str) -> str:
    return INK_TRACE_TREASURE_NAMES.get(image, "无名墨宝")


def calculate_ink_trace_reward_wine(stake_wine: int, image: str) -> int:
    return stake_wine * get_ink_trace_reward_tenths(image) // 10


def calculate_ink_trace_stargaze_cost(stake_wine: int) -> int:
    return max(1, stake_wine * INK_TRACE_STARGAZE_TENTHS // 10)


def choose_ink_trace_treasure(options: list[str]) -> str:
    return random.choices(
        options,
        weights=[INK_TRACE_TREASURE_WEIGHTS[option] for option in options],
        k=1,
    )[0]


def new_ink_trace_game(stake_wine: int, user_id: str, group_id: str, nickname: str) -> dict:
    option_count = random.choice(INK_TRACE_OPTION_COUNTS)
    options = random.sample(INK_TRACE_IMAGES, option_count)
    treasure = choose_ink_trace_treasure(options)
    return {
        "options": options,
        "treasure": treasure,
        "excluded": [],
        "stargazed": False,
        "stake_wine": stake_wine,
        "user_id": user_id,
        "group_id": group_id,
        "nickname": nickname,
        "started_at": time.time(),
    }


def reveal_wrong_ink_trace_option(game: dict) -> str | None:
    excluded = set(game.get("excluded", []))
    candidates = [option for option in game["options"] if option != game["treasure"] and option not in excluded]
    if not candidates:
        return None
    revealed = random.choice(candidates)
    game.setdefault("excluded", []).append(revealed)
    game["stargazed"] = True
    return revealed


def _posterior_weight_for_bad_count(
    bad_count: int,
    revealed_good_count: int,
    mode: str | int = RANDOM_MODE,
) -> float:
    total_good = SIGN_COUNT - bad_count
    if revealed_good_count > total_good:
        return 0.0
    weight = get_mode_bad_weights(mode).get(bad_count, 0)
    return weight * comb(total_good, revealed_good_count) / comb(SIGN_COUNT, revealed_good_count)


def calculate_continue_expectation_wine(
    stake_wine: int,
    revealed_good_count: int,
    mode: str | int = RANDOM_MODE,
) -> float:
    hidden_count = SIGN_COUNT - revealed_good_count
    if hidden_count <= 0:
        return 0.0

    weighted_good_probability = 0.0
    total_weight = 0.0
    for bad_count in get_mode_bad_weights(mode):
        weight = _posterior_weight_for_bad_count(bad_count, revealed_good_count, mode)
        if weight <= 0:
            continue
        remaining_good = SIGN_COUNT - bad_count - revealed_good_count
        weighted_good_probability += weight * max(remaining_good, 0) / hidden_count
        total_weight += weight

    if total_weight <= 0:
        return 0.0
    good_probability = weighted_good_probability / total_weight
    return good_probability * calculate_reward_wine(stake_wine, revealed_good_count + 1, mode)


def calculate_optimal_return_ratio(mode: str | int = RANDOM_MODE) -> float:
    cache: dict[int, float] = {}
    multipliers = get_mode_multipliers(mode)
    max_good_count = max(SIGN_COUNT - bad_count for bad_count in get_mode_bad_weights(mode))

    def best_return(good_count: int) -> float:
        if good_count in cache:
            return cache[good_count]

        cash_out = 0.0 if good_count <= 0 else multipliers[min(good_count, len(multipliers)) - 1] / 10
        if good_count >= max_good_count:
            cache[good_count] = cash_out
            return cash_out

        hidden_count = SIGN_COUNT - good_count
        continue_return = 0.0
        total_weight = 0.0
        for bad_count in get_mode_bad_weights(mode):
            weight = _posterior_weight_for_bad_count(bad_count, good_count, mode)
            if weight <= 0:
                continue
            remaining_good = SIGN_COUNT - bad_count - good_count
            continue_return += weight * max(remaining_good, 0) / hidden_count * best_return(good_count + 1)
            total_weight += weight

        if total_weight > 0:
            continue_return /= total_weight
        cache[good_count] = max(cash_out, continue_return)
        return cache[good_count]

    return best_return(0)


def current_multiplier_text(good_count: int, mode: str | int = RANDOM_MODE) -> str:
    if good_count <= 0:
        return "0x"
    multipliers = get_mode_multipliers(mode)
    tenths = multipliers[min(good_count, len(multipliers)) - 1]
    if tenths % 10 == 0:
        return f"{tenths // 10}x"
    value = tenths / 10
    return f"{value:.2f}".rstrip("0").rstrip(".") + "x"


def mode_multiplier_text(mode: str | int = RANDOM_MODE) -> str:
    return "｜".join(current_multiplier_text(index + 1, mode) for index in range(len(get_mode_multipliers(mode))))


def _format_board(game: dict, reveal_all: bool = False) -> str:
    cells = []
    revealed = set(game.get("revealed", []))
    deck = game["deck"]
    for index, sign in enumerate(deck):
        if reveal_all or index in revealed:
            face = "吉" if sign == "吉" else "凶"
        else:
            face = "?"
        cells.append(f"{index + 1}.{face}")
    return "  ".join(cells)


def _format_ink_trace_options(game: dict) -> str:
    excluded = set(game.get("excluded", []))
    return "  ".join(f"{option}{'（空）' if option in excluded else ''}" for option in game["options"])


def _status_line(game: dict) -> str:
    good_count = int(game.get("good_count", 0))
    mode = game.get("mode", RANDOM_MODE)
    reward = calculate_reward_wine(game["stake_wine"], good_count, mode)
    return (
        f"已翻吉签：{good_count}/{SIGN_COUNT}\n"
        f"当前倍率：{current_multiplier_text(good_count, mode)}\n"
        f"当前可收：{reward} 酒钱"
    )


def _render_tavern_help() -> str:
    return (
        "🍶 太白酒馆 🍶\n"
        f"{'=' * 20}\n"
        "（本猫推开木门，酒旗在檐下慢慢晃）进了太白酒馆，先认这枚酒钱。\n"
        "积分可在柜上添作酒钱：1 积分，换 10 酒钱。\n"
        "酒钱入了壶，便在馆中流转；今日翻签，来日添新局，也都从这只酒壶里斟。\n"
        f"{'=' * 20}\n"
        "/酒钱 - 查看酒馆酒钱\n"
        "/兑换酒钱 积分数 - 添酒钱入壶\n"
        "/灵签翻盘 酒钱数 [凶签数] - 入灵签桌\n"
        "/墨宝寻踪 酒钱数 - 入旧卷寻墨宝\n"
        f"{'=' * 20}\n"
        "灵签翻盘：五签覆面，自选其一翻开；吉签可收，凶签清桌。\n"
        "不写凶签数，便听酒馆随机排签；写 1-4，则凶签越多，彩头越高。\n"
        "墨宝寻踪：本猫把不同墨宝藏进酒、月、剑、花、云、舟之中；各有轻重，也各有彩头。\n"
        f"{'=' * 20}\n"
        "『酒旗斜挂月初明，\n"
        "一分换得十钱声。\n"
        "莫问杯中归旧账，\n"
        "且留馆里续新程。』"
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
    stake_result = prepare_wine_stake(user_id, group_id, wine_money)
    if stake_result["status"] == "insufficient_wine":
        await start_flip.finish(
            "（拨了拨酒馆账珠）这桌酒钱还差些。\n"
            f"入场需：{wine_money} 酒钱\n"
            f"现有酒钱：{stake_result['wine_balance']}\n"
            f"还差酒钱：{stake_result['shortfall']}（可先用 /兑换酒钱 {stake_result['point_cost']} 添酒）\n"
            "『酒未入壶桌不开，先添一盏再翻签。』"
        )

    if stake_result["status"] != "ok":
        await start_flip.finish(
            "（账珠忽停）这笔酒钱暂未落桌，请稍后再试。\n"
            "『算盘偶乱杯中月，重来一声便可开。』"
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
        f"酒钱余额：{stake_result['wine_balance']}\n"
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
        active_games.pop(game_key, None)
        reward = calculate_reward_wine(game["stake_wine"], max_good_count, mode)
        if reward > 0:
            record = add_wine_money(game["user_id"], game["group_id"], reward)
        else:
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
        active_games.pop(game_key, None)
        reward = calculate_reward_wine(game["stake_wine"], good_count, mode)
        record = add_wine_money(game["user_id"], game["group_id"], reward)
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

    game = active_games.pop(game_key)
    good_count = int(game.get("good_count", 0))
    if good_count <= 0:
        refund = calculate_refund_wine(game["stake_wine"])
        if refund > 0:
            record = add_wine_money(game["user_id"], game["group_id"], refund)
        else:
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
    record = add_wine_money(game["user_id"], game["group_id"], reward)
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

    game = active_games.pop(game_key)
    refund = calculate_refund_wine(game["stake_wine"])
    if refund > 0:
        record = add_wine_money(game["user_id"], game["group_id"], refund)
    else:
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

    stake_result = prepare_wine_stake(user_id, group_id, wine_money)
    if stake_result["status"] == "insufficient_wine":
        await start_ink_trace.finish(
            "（本猫摸了摸酒壶）这回寻墨的酒钱还差些。\n"
            f"入卷需：{wine_money} 酒钱\n"
            f"现有酒钱：{stake_result['wine_balance']}\n"
            f"还差酒钱：{stake_result['shortfall']}（可先用 /兑换酒钱 {stake_result['point_cost']} 添酒）\n"
            "『壶中未满难开卷，先添一盏再寻诗。』"
        )

    if stake_result["status"] != "ok":
        await start_ink_trace.finish(
            "（旧卷边角忽然一皱）这笔酒钱暂未落案，请稍后再试。\n"
            "『墨痕偶被灯花乱，重来一声便可寻。』"
        )

    nickname = await get_nickname(bot, user_id, context="太白酒馆")
    game = new_ink_trace_game(wine_money, user_id, group_id, nickname)
    active_ink_traces[game_key] = game
    stargaze_cost = calculate_ink_trace_stargaze_cost(wine_money)

    await start_ink_trace.finish(
        "🍶 太白酒馆·墨宝寻踪 🍶\n"
        f"{'=' * 20}\n"
        "（本猫翻开一轴旧卷，又把酒壶往袖中一藏）墨痕已藏，且看谁能寻到诗眼。\n"
        f"玩家：{nickname}\n"
        f"入卷：{wine_money} 酒钱\n"
        f"酒钱余额：{stake_result['wine_balance']}\n"
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
    spend_result = spend_wine_money(game["user_id"], game["group_id"], cost)
    if not spend_result["ok"]:
        await stargaze_ink_trace.finish(
            "（本猫摸了摸酒壶）观星还差一点酒钱。\n"
            f"观星需：{cost} 酒钱\n"
            f"现有酒钱：{spend_result['balance']}\n"
            "『星盘也要沾杯气，添些酒钱再问天。』"
        )

    revealed = reveal_wrong_ink_trace_option(game)
    if revealed is None:
        await stargaze_ink_trace.finish(
            "（星光落到卷心）这一卷已无可排的空意象。\n"
            f"酒钱余额：{spend_result['balance']}"
        )

    await stargaze_ink_trace.finish(
        "🍶 太白酒馆·墨宝观星 🍶\n"
        f"{'=' * 20}\n"
        "（本猫眯眼望星，袖中旧卷沙沙一响）这处没有墨宝。\n"
        f"排除：{revealed}\n"
        f"消耗：{cost} 酒钱\n"
        f"酒钱余额：{spend_result['balance']}\n"
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

    active_ink_traces.pop(game_key, None)
    if guess == game["treasure"]:
        reward = calculate_ink_trace_reward_wine(game["stake_wine"], game["treasure"])
        record = add_wine_money(game["user_id"], game["group_id"], reward)
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
