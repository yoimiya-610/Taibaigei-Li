"""Pure parsing and reward rules for Taibai Tavern."""

import asyncio
import random
import re
import time
from math import ceil, comb
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

FLIP_GAME_TYPE = "tavern_flip"
INK_GAME_TYPE = "tavern_ink"
RPS_GAME_TYPE = "tavern_rps_duel"
FEATURE_KEY = "taibai_tavern"

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
RPS_CHALLENGE_TIMEOUT_SECONDS = 60
RPS_RESULT_DEADLINE_SECONDS = 30
RPS_FETCH_ATTEMPTS = 3
RPS_FETCH_DELAY_SECONDS = 0.2
RPS_RESULT_NAMES = {1: "石头", 2: "剪刀", 3: "布"}
RANDOM_MODE = "random"
FIXED_BAD_SIGN_COUNTS = (1, 2, 3, 4)
MODE_MULTIPLIER_TENTHS = {
    RANDOM_MODE: (11, 15, 23, 38, 75),
    1: (10, 12.5, 17, 25),
    2: (13, 20, 60),
    3: (20, 80),
    4: (40,),
}

BAD_SIGN_PRIOR_WEIGHTS = {
    0: BAD_SIGN_ZERO_WEIGHT,
    1: BAD_SIGN_ONE_WEIGHT,
    2: BAD_SIGN_TWO_WEIGHT,
}

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


def parse_rps_challenge_args(args: Message) -> dict | None:
    targets = []
    for segment in args:
        if segment.type != "at":
            continue
        target_id = str(segment.data.get("qq", "")).strip()
        if target_id and target_id != "all":
            targets.append(target_id)
    if len(targets) != 1:
        return None

    stake_wine = parse_wine_money(args.extract_plain_text())
    if stake_wine is None:
        return None
    return {"target_id": targets[0], "stake_wine": stake_wine}


def compare_rps(first: int, second: int) -> int:
    if first == second:
        return 0
    if (first, second) in {(1, 2), (2, 3), (3, 1)}:
        return 1
    return -1


def _extract_message_id(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    message_id = response.get("message_id")
    if message_id is None and isinstance(response.get("data"), dict):
        message_id = response["data"].get("message_id")
    if message_id is None or not str(message_id).strip():
        return None
    return str(message_id).strip()


def _normalize_rps_result(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result in RPS_RESULT_NAMES else None


def _extract_rps_result(value: Any) -> int | None:
    if isinstance(value, MessageSegment):
        if value.type == "rps":
            return _normalize_rps_result(value.data.get("result"))
        return None

    if isinstance(value, Message):
        for segment in value:
            result = _extract_rps_result(segment)
            if result is not None:
                return result
        return None

    if isinstance(value, dict):
        if value.get("type") == "rps" and isinstance(value.get("data"), dict):
            return _normalize_rps_result(value["data"].get("result"))
        for key in ("message", "raw_message"):
            if key in value:
                result = _extract_rps_result(value[key])
                if result is not None:
                    return result
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            result = _extract_rps_result(item)
            if result is not None:
                return result
        return None

    if isinstance(value, str):
        match = re.search(r"\[CQ:rps(?:,[^\]]*?)?result=([1-3])(?:,[^\]]*)?\]", value)
        if match:
            return int(match.group(1))
    return None


class QQRpsResultError(RuntimeError):
    """Raised when a native QQ rock-paper-scissors result cannot be recovered safely."""


async def _read_qq_rps_result(bot: Bot, message_id: str) -> int:
    last_error: Exception | None = None
    for attempt in range(RPS_FETCH_ATTEMPTS):
        try:
            message = await bot.get_msg(message_id=message_id)
            result = _extract_rps_result(message)
            if result is not None:
                return result
        except Exception as exc:
            last_error = exc

        if attempt + 1 < RPS_FETCH_ATTEMPTS:
            await asyncio.sleep(RPS_FETCH_DELAY_SECONDS)

    error = QQRpsResultError(f"无法读取 QQ 猜拳结果 message_id={message_id}")
    if last_error is not None:
        raise error from last_error
    raise error


def _challenge_expired(challenge: dict, *, now: float | None = None) -> bool:
    current_time = time.time() if now is None else float(now)
    return current_time >= float(challenge["expires_at"])


def _rps_result_name(result: int) -> str:
    return RPS_RESULT_NAMES.get(result, "拳影不明")


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
