from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="legacy_race",
    name="赛博竞速",
    default_enabled=False,
    scope="group",
    permission_level=4,
    data_files=("data/paid_rounds.json", "data/points.json"),
    privacy_level="personal",
    backup_policy="standard",
)

import random
import asyncio
import time

from nonebot import get_bots, on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from nonebot.rule import Rule
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.accounting import ASSET_POINTS, get_points
from mybot.common.paid_rounds import (
    PaidRoundService,
    new_round_id,
    register_recovery_adapter,
)
from mybot.plugins.rate_limit import check_game_limit, get_limit_message
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)
FEATURE_KEY = "legacy_race"
GAME_TYPE = "race"
MAX_BET = 100
POOL_PAYOUT_RATE = 0.95
MIN_RETURN_MULTIPLIER = 1.9
FINISH_LINE = 20
PROGRESS_CELLS = 10
EVENT_CHANCE = 0.10
STORY_DELAY_SECONDS = 1.5
LANE_MARKERS = ("①", "②", "③", "④", "⑤", "⑥")
STORY_PHASES = ("第一幕·鸣铃起势", "第二幕·月影弯道", "第三幕·破晓冲线")
HELP_ITEMS = (
    HelpItem("小游戏", "/赛博竞速 - 赛博竞速", 50),
)
COMMAND_ALIASES = (
    "赛博竞速",
    "竞速",
    "开始竞速",
    "选马",
    "选择竞速",
    "开跑",
    "开始跑",
    "取消竞速",
)


async def _feature_enabled(event: MessageEvent) -> bool:
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    return is_feature_enabled(FEATURE_KEY, group_id)


FEATURE_RULE = Rule(_feature_enabled)

# 存储进行中的比赛 {group_id: {"players": {}, "started": False, "horses": []}}
active_races = {}


def _round_service() -> PaidRoundService:
    return PaidRoundService()


def _hydrate_round(round_record: dict) -> dict:
    race = round_record["payload"]
    race["round_id"] = round_record["round_id"]
    players = race.setdefault("players", {})
    for participant in round_record.get("participants", {}).values():
        if participant.get("state") not in {"active", "settled"}:
            continue
        metadata = participant.get("metadata", {})
        if metadata.get("role") != "bet":
            continue
        players.setdefault(
            participant["user_id"],
            {
                "nickname": metadata["nickname"],
                "horse": metadata["horse"],
                "amount": participant["amount"],
            },
        )
    race.pop("settlement_running", None)
    return race


def _restore_round(round_record: dict, service: PaidRoundService) -> None:
    active_races[round_record["group_id"]] = _hydrate_round(round_record)


def _round_is_loaded(round_record: dict) -> bool:
    return active_races.get(round_record["group_id"], {}).get("round_id") == round_record["round_id"]


def _discard_round(round_record: dict, service: PaidRoundService) -> None:
    if _round_is_loaded(round_record):
        active_races.pop(round_record["group_id"], None)


def _connected_bot() -> Bot | None:
    return next(iter(get_bots().values()), None)


async def _settle_due_round(round_record: dict, service: PaidRoundService) -> None:
    if not _round_is_loaded(round_record):
        _restore_round(round_record, service)
    race = active_races.get(round_record["group_id"])
    if race and race.get("settlement_running"):
        return
    if race and race.get("players"):
        await run_race(_connected_bot(), round_record["group_id"], animate=False)
    elif race:
        service.expire_round(round_record["round_id"], reason="no_participants")
        active_races.pop(round_record["group_id"], None)


register_recovery_adapter(
    GAME_TYPE,
    restore=_restore_round,
    is_loaded=_round_is_loaded,
    discard=_discard_round,
    on_due=_settle_due_round,
)

# 参赛选手
HORSES = [
    {"emoji": "🐎", "name": "烈焰神驹"},
    {"emoji": "🦄", "name": "独角幻兽"},
    {"emoji": "🐢", "name": "玄武龟龟"},
    {"emoji": "🐇", "name": "闪电兔兔"},
    {"emoji": "🐌", "name": "蜗牛冲刺"},
    {"emoji": "🦊", "name": "九尾狐仙"},
]

# 选手风格只影响速度曲线，不写入持久化赛局，旧赛局可继续按名字恢复。
RACER_PROFILES = {
    "烈焰神驹": {
        "style": "爆发型",
        "description": "忽缓忽疾，最会在眨眼间窜出一程",
        "pace": "burst",
    },
    "独角幻兽": {
        "style": "均衡型",
        "description": "步法圆融，前后程皆无明显短板",
        "pace": "balanced",
    },
    "玄武龟龟": {
        "style": "稳健型",
        "description": "不争一时快慢，胜在步步都算数",
        "pace": "steady",
    },
    "闪电兔兔": {
        "style": "前程型",
        "description": "起步如雷，越过半程后更讲究守势",
        "pace": "front_runner",
    },
    "蜗牛冲刺": {
        "style": "后程型",
        "description": "前半程藏锋，临近终点才亮出真本事",
        "pace": "closer",
    },
    "九尾狐仙": {
        "style": "诡变型",
        "description": "脚步最难捉摸，停云与飞星只隔一瞬",
        "pace": "chaotic",
    },
}
DEFAULT_RACER_PROFILE = {
    "style": "均衡型",
    "description": "步法圆融，前后程皆无明显短板",
    "pace": "balanced",
}

# 赛博诗酒风格事件；正负效果成对出现，避免事件池天然偏向某一方向。
EVENTS = [
    {"icon": "⚡", "text": "{name}踏中月光超频阵，剑气陡增！", "effect": 3},
    {"icon": "🌫️", "text": "{name}闯进量子迷雾，方向一时难辨。", "effect": -3},
    {"icon": "🌙", "text": "{name}借月影抄过弯心，身法轻快！", "effect": 2},
    {"icon": "🍶", "text": "{name}被酒雾遮住前路，脚步微乱。", "effect": -2},
    {"icon": "🗡️", "text": "{name}循着青莲剑光破风而行！", "effect": 1},
    {"icon": "🪶", "text": "{name}接住飞来的诗笺，分神读了一眼。", "effect": -1},
]

# 开赛文案
START_MESSAGES = [
    "（敲锣）诸位诸位！赛博竞速即将开始！快来选择！",
    "（推墨镜）又到了见证奇迹的时刻~谁是今日的幸运儿？",
    "（晃酒壶）人生如竞速，不选择怎知结果？来来来~",
    "（甩袖）风萧萧兮易水寒，竞速一去兮不复还...等等，选择了吗？",
]

# 参与成功文案
BET_SUCCESS = [
    "（点头）好眼光！本猫也看好这匹~",
    "（抛媚眼）选它？和本猫心有灵犀嘛~",
    "（举杯）有魄力！来，先干一杯壮行酒~",
    "（拍肩）勇气可嘉，希望它不会让你失望~",
]

# 比赛开始文案
RACE_START_MESSAGES = [
    "（举提示牌）各就各位——预备——叮！！！",
    "（挥旗）比赛开始！让我们见证速度与激情！",
    "（敲钟）号角响起！命运的赛道已经铺开！",
]

# 冠军揭晓文案
WINNER_ANNOUNCE = [
    "（撒花）冠军诞生！让我们恭喜——",
    "（激动）太精彩了！胜者为王——",
    "（鼓掌）尘埃落定！今日王者——",
]

# 选中文案
BET_WIN_MESSAGES = [
    "（竖大拇指）好眼光！本猫就知道你行！",
    "（鼓掌）恭喜恭喜！慧眼识英雄啊~",
    "（抛媚眼）得分了？今晚要不要请本猫喝一杯？",
]

# 没选中文案
BET_LOSE_MESSAGES = [
    "（摇头）可惜可惜，下次再来~",
    "（递手帕）别难过，本猫借你肩膀靠靠？",
    "（安慰）胜败乃兵家常事，本猫依然爱你~",
]

# 无人参与文案
NO_BET_MESSAGES = [
    "（委屈）没人选择...选手们白跑了...",
    "（叹气）赛博竞速取消，本猫去喝闷酒了...",
    "（收起旗子）没人捧场，本猫好寂寞...",
]


def _get_racer_profile(horse: dict) -> dict:
    return RACER_PROFILES.get(horse.get("name"), DEFAULT_RACER_PROFILE)


def _format_horse_roster(horses: list[dict]) -> str:
    lines = []
    for index, horse in enumerate(horses):
        profile = _get_racer_profile(horse)
        lines.append(f"{index + 1}. {horse['emoji']} {horse['name']}｜{profile['style']}")
        lines.append(f"   {profile['description']}")
    return "\n".join(lines)


def _roll_base_speed(rng: random.Random, horse: dict, position: int) -> int:
    pace = _get_racer_profile(horse)["pace"]
    if pace == "burst":
        return rng.choice((1, 1, 2, 3, 4, 4))
    if pace == "steady":
        return rng.choice((2, 2, 2, 2, 3, 3, 3, 4))
    if pace == "front_runner":
        return rng.choice((2, 3, 4, 4) if position < FINISH_LINE / 2 else (1, 2, 2, 3))
    if pace == "closer":
        return rng.choice((1, 2, 2, 3) if position < FINISH_LINE * 0.4 else (2, 3, 4, 4))
    if pace == "chaotic":
        return rng.choice((0, 0, 1, 2, 3, 4, 4, 5))
    return rng.randint(1, 4)


def _render_progress_bar(position: int) -> str:
    clamped = max(0, min(position, FINISH_LINE))
    if clamped >= FINISH_LINE:
        filled = PROGRESS_CELLS
    else:
        filled = min(
            PROGRESS_CELLS - 1,
            (clamped * PROGRESS_CELLS + FINISH_LINE - 1) // FINISH_LINE,
        )
    return "■" * filled + "□" * (PROGRESS_CELLS - filled)


def _render_race_board(horses: list[dict], positions: list[int]) -> str:
    lines = []
    for index, (horse, position) in enumerate(zip(horses, positions)):
        marker = LANE_MARKERS[index] if index < len(LANE_MARKERS) else f"{index + 1}."
        lines.append(f"{marker} {horse['name']} {position:02d}/{FINISH_LINE} {horse['emoji']}")
        lines.append(f"   {_render_progress_bar(position)}")
    return "\n".join(lines)


def _rank_results(seed: int, positions: list[int], finish_times: list[float | None]) -> list[tuple[int, int]]:
    """Rank simultaneous finishers by exact crossing time, then by a seeded tie-break."""

    def sort_key(index: int) -> tuple[float, float, float]:
        tie_breaker = random.Random(f"{seed}:race-rank:{index}").random()
        finish_time = finish_times[index]
        if finish_time is not None:
            return (0.0, finish_time, tie_breaker)
        return (1.0, -float(positions[index]), tie_breaker)

    ordered_indices = sorted(range(len(positions)), key=sort_key)
    return [(index, positions[index]) for index in ordered_indices]


def _build_commentary(
    horses: list[dict],
    previous_positions: list[int],
    positions: list[int],
    seed: int,
    *,
    winner_idx: int | None = None,
) -> str:
    current_order = [index for index, _ in _rank_results(seed, positions, [None] * len(positions))]
    previous_order = [
        index for index, _ in _rank_results(seed, previous_positions, [None] * len(previous_positions))
    ]

    if winner_idx is not None:
        return f"🏁 {horses[winner_idx]['name']}踏碎终点光栅，今夜先饮头杯！"

    if not any(previous_positions):
        return f"🎙️ {horses[current_order[0]]['name']}先声夺人，抢到第一缕月光！"

    if previous_order[0] != current_order[0]:
        leader = horses[current_order[0]]["name"]
        return f"🎙️ {leader}踏月反超，夺下领跑位！"

    previous_rank = {horse_index: rank for rank, horse_index in enumerate(previous_order)}
    gains = [(previous_rank[horse_index] - rank, horse_index) for rank, horse_index in enumerate(current_order)]
    gain, climber_idx = max(gains)
    if gain > 0:
        return f"🎙️ {horses[climber_idx]['name']}一口气追过 {gain} 位，剑气正盛！"

    leader_idx = current_order[0]
    if len(current_order) > 1:
        gap = positions[leader_idx] - positions[current_order[1]]
        if gap <= 1:
            return "🎙️ 前二只差一步，酒盏尚未落桌！"
    return f"🎙️ {horses[leader_idx]['name']}暂执先手，身后风声紧得很。"


def _build_story_frames(simulation: dict, horses: list[dict], seed: int) -> list[dict]:
    frames = simulation["frames"]
    if not frames:
        return []

    if len(frames) == 1:
        endpoints = [0]
        phases = [STORY_PHASES[-1]]
    elif len(frames) == 2:
        endpoints = [0, 1]
        phases = [STORY_PHASES[0], STORY_PHASES[-1]]
    else:
        endpoints = [0, (len(frames) - 1) // 2, len(frames) - 1]
        phases = list(STORY_PHASES)

    story_frames = []
    segment_start = 0
    previous_positions = [0] * len(horses)
    for phase, endpoint in zip(phases, endpoints):
        source = frames[endpoint]
        events = [
            event
            for frame in frames[segment_start : endpoint + 1]
            for event in frame["events"]
        ]
        winner_idx = simulation["winner_idx"] if endpoint == len(frames) - 1 else None
        story_frames.append(
            {
                "phase": phase,
                "round": source["round"],
                "positions": source["positions"],
                "visual": source["visual"],
                "events": events,
                "commentary": _build_commentary(
                    horses,
                    previous_positions,
                    source["positions"],
                    seed,
                    winner_idx=winner_idx,
                ),
            }
        )
        previous_positions = source["positions"]
        segment_start = endpoint + 1
    return story_frames


# 开始比赛
start_race = on_command("赛博竞速", aliases={"竞速", "开始竞速"}, rule=FEATURE_RULE, priority=5, block=True)

@start_race.handle()
async def handle_start_race(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await start_race.finish("（摇头）赛博竞速要在群里才热闹嘛~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 检查是否已有比赛
    if group_id in active_races:
        race = active_races[group_id]
        if race["started"]:
            await start_race.finish("（指向赛道）赛博竞速正在进行中！先看完这场再说~")
        else:
            horses_list = _format_horse_roster(race["horses"])
            await start_race.finish(
                f"（敲桌子）已经有比赛等着开跑了！\n"
                f"{'='*20}\n"
                f"{horses_list}\n"
                f"{'='*20}\n"
                f"/选马 编号 金额 - 参与\n"
                f"例：/选马 1 30"
            )
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"赛博竞速创建获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 随机选4匹马参赛
    horses = random.sample(HORSES, 4)
    
    # 创建比赛
    active_races[group_id] = {
        "players": {},
        "started": False,
        "horses": horses,
        "starter": nickname,
        "seed": random.getrandbits(64),
    }
    service = _round_service()
    round_id = new_round_id(GAME_TYPE)
    active_races[group_id]["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=GAME_TYPE,
        mode="timed",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_POINTS,
        feature_key=FEATURE_KEY,
        payload=active_races[group_id],
        deadline_at=time.time() + 30,
    )
    
    horses_list = _format_horse_roster(horses)
    start_msg = random.choice(START_MESSAGES)
    
    await start_race.send(
        f"🏇 李太白给·赛博竞速 🏇\n"
        f"{'='*20}\n"
        f"📢 {nickname} 发起了赛博竞速！\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"今日参赛选手：\n\n"
        f"{horses_list}\n"
        f"{'='*20}\n"
        f"🎟️ 30秒内选择选手：\n"
        f"/选马 编号 金额\n"
        f"例：/选马 1 30\n"
        f"{'='*20}\n"
        f"单次最高 {MAX_BET} 积分\n"
        f"/开跑 - 提前开始\n"
        f"『竞速场上风云起，\n谁家选手夺桂冠？\n选择全凭眼力劲，\n结果不过一念间~』"
    )
    
    # 30秒后自动开跑
    asyncio.create_task(auto_start_race(bot, group_id))

async def auto_start_race(bot: Bot, group_id: str):
    """30秒后自动开始比赛"""
    await asyncio.sleep(30)
    
    if group_id in active_races and not active_races[group_id]["started"]:
        if active_races[group_id]["players"]:
            await run_race(bot, group_id)
        else:
            _round_service().expire_round(active_races[group_id]["round_id"], reason="no_participants")
            active_races.pop(group_id, None)
            try:
                msg = random.choice(NO_BET_MESSAGES)
                await bot.send_group_msg(group_id=int(group_id), message=f"🏇 赛博竞速取消 🏇\n{'='*20}\n{msg}")
            except Exception as exc:
                logger.exception(f"发送赛博竞速无人参与取消消息失败 group_id={group_id}: {exc}")

# 参与
bet_horse = on_command("选马", aliases={"选择竞速"}, rule=FEATURE_RULE, priority=5, block=True)

@bet_horse.handle()
async def handle_bet_horse(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await bet_horse.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in active_races:
        await bet_horse.finish("（摊手）当前没有赛博竞速，输入 /赛博竞速 开一局？")
    
    race = active_races[group_id]
    
    if race["started"]:
        await bet_horse.finish("（摇头）比赛已经开始了，下次早点来~")
    
    # 检查是否已参与
    if user_id in race["players"]:
        old = race["players"][user_id]
        horse = race["horses"][old["horse"]]
        await bet_horse.finish(f"（戳你）你已经选了 {horse['emoji']}{horse['name']} {old['amount']}积分，不能改了~")
    
    # 解析参数
    params = args.extract_plain_text().strip().split()
    
    if len(params) < 2:
        await bet_horse.finish("（敲你头）格式：/选马 编号 金额\n例：/选马 1 30")
    
    try:
        horse_num = int(params[0])
        bet_amount = int(params[1])
        if horse_num < 1 or horse_num > len(race["horses"]):
            raise ValueError("编号错误")
        if bet_amount <= 0:
            raise ValueError("金额错误")
    except ValueError:
        await bet_horse.finish("（无语）请输入正确的编号和金额！")
    
    if bet_amount > MAX_BET:
        await bet_horse.finish("（摇手指）单次最多100积分！")

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await bet_horse.finish(get_limit_message(result))
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"赛博竞速参与获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet_amount:
        await bet_horse.finish(f"（摇头）积分不够...你只有 {points_info['current']} 积分")
    
    player_record = {
        "nickname": nickname,
        "horse": horse_num - 1,
        "amount": bet_amount
    }
    service = _round_service()
    service.add_participant(
        race["round_id"],
        participant_id=user_id,
        user_id=user_id,
        amount=bet_amount,
        metadata={
            "role": "bet",
            "nickname": nickname,
            "horse": horse_num - 1,
        },
    )
    charge = service.freeze_participant(race["round_id"], user_id)
    if not charge["ok"]:
        await bet_horse.finish(f"（摇头）积分不够...你只有 {charge['balance']} 积分")
    race["players"][user_id] = player_record
    service.update_payload(race["round_id"], race)
    
    horse = race["horses"][horse_num - 1]
    bet_msg = random.choice(BET_SUCCESS)
    
    # 统计各马参与情况
    bets_summary = {}
    for i, h in enumerate(race["horses"]):
        total = sum(p["amount"] for p in race["players"].values() if p["horse"] == i)
        if total > 0:
            bets_summary[i] = total
    
    summary_text = "\n".join([
        f"{race['horses'][i]['emoji']} {race['horses'][i]['name']}：{amt}积分"
        for i, amt in bets_summary.items()
    ])
    
    await bet_horse.finish(
        f"✅ {nickname} 选 {horse['emoji']}{horse['name']} {bet_amount}积分！\n"
        f"{bet_msg}\n"
        f"{'='*20}\n"
        f"当前参与：\n"
        f"{summary_text}\n"
        f"共 {len(race['players'])} 人参与"
    )

# 开跑
go_race = on_command("开跑", aliases={"开始跑"}, rule=FEATURE_RULE, priority=5, block=True)

@go_race.handle()
async def handle_go_race(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await go_race.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_races:
        await go_race.finish("（摊手）当前没有赛博竞速！")
    
    race = active_races[group_id]
    
    if race["started"]:
        await go_race.finish("（指向赛道）比赛已经在进行中了！")
    
    if not race["players"]:
        _round_service().expire_round(race["round_id"], reason="no_participants")
        active_races.pop(group_id, None)
        await go_race.finish("（叹气）没人参与，比赛取消~")
    
    await run_race(bot, group_id)

def _simulate_race(race: dict) -> dict:
    """Use the persisted seed to make the complete race outcome reproducible."""
    rng = random.Random(race["seed"])
    horses = race["horses"]
    positions = [0] * len(horses)
    finish_times: list[float | None] = [None] * len(horses)
    frames = []
    round_num = 0

    while max(positions) < FINISH_LINE:
        round_num += 1
        event_messages = []
        for index in range(len(horses)):
            if finish_times[index] is not None:
                continue
            previous_position = positions[index]
            base_speed = _roll_base_speed(rng, horses[index], previous_position)
            speed = base_speed
            if rng.random() < EVENT_CHANCE:
                event = rng.choice(EVENTS)
                speed = max(0, base_speed + event["effect"])
                actual_effect = speed - base_speed
                event_messages.append(
                    f"{event['icon']} {event['text'].format(name=horses[index]['name'])}"
                    f"（步幅 {actual_effect:+d}）"
                )

            raw_position = previous_position + speed
            if speed > 0 and raw_position >= FINISH_LINE:
                finish_times[index] = (round_num - 1) + (FINISH_LINE - previous_position) / speed
            positions[index] = min(raw_position, FINISH_LINE)

        frames.append(
            {
                "round": round_num,
                "positions": positions.copy(),
                "visual": _render_race_board(horses, positions),
                "events": event_messages,
            }
        )

    results = _rank_results(race["seed"], positions, finish_times)
    return {
        "positions": positions,
        "finish_times": finish_times,
        "results": results,
        "winner_idx": results[0][0],
        "frames": frames,
    }


async def run_race(bot: Bot | None, group_id: str, *, animate: bool = True):
    """Persist a deterministic result, then animate and settle exactly once."""
    if group_id not in active_races:
        return

    race = active_races[group_id]
    if race.get("settlement_running"):
        return
    race["started"] = True
    race["settlement_running"] = True
    horses = race["horses"]
    simulation = _simulate_race(race)
    results = simulation["results"]
    winner_idx = simulation["winner_idx"]
    winner = horses[winner_idx]

    winners = []
    losers = []
    payouts = {}
    total_pool = sum(player["amount"] for player in race["players"].values())
    winner_pool = sum(
        player["amount"]
        for player in race["players"].values()
        if player["horse"] == winner_idx
    )

    for user_id, bet_info in race["players"].items():
        nickname = bet_info["nickname"]
        bet_amount = bet_info["amount"]
        if bet_info["horse"] == winner_idx:
            if winner_pool > 0:
                win_ratio = bet_amount / winner_pool
                win_amount = max(
                    int(total_pool * win_ratio * POOL_PAYOUT_RATE),
                    int(bet_amount * MIN_RETURN_MULTIPLIER),
                )
            else:
                win_amount = int(bet_amount * MIN_RETURN_MULTIPLIER)
            payouts[user_id] = win_amount
            winners.append(f"🎉 {nickname}：+{win_amount - bet_amount}")
        else:
            losers.append(f"💀 {nickname}：-{bet_amount}")

    service = _round_service()
    persisted_payload = dict(race)
    persisted_payload.pop("settlement_running", None)
    service.update_payload(race["round_id"], persisted_payload)
    service.prepare_settlement(
        race["round_id"],
        result={
            "winner_idx": winner_idx,
            "positions": simulation["positions"],
            "finish_times": simulation["finish_times"],
            "results": results,
        },
        payouts=payouts,
    )

    if animate and bot is not None:
        try:
            await bot.send_group_msg(
                group_id=int(group_id),
                message=f"🏇 赛博竞速开始！🏇\n{'='*20}\n{random.choice(RACE_START_MESSAGES)}",
            )
        except Exception as exc:
            logger.exception(f"发送赛博竞速开始消息失败 group_id={group_id}: {exc}")
        await asyncio.sleep(1)

        for frame in _build_story_frames(simulation, horses, race["seed"]):
            msg = f"🏇 {frame['phase']}（第{frame['round']}轮）🏇\n{'='*20}\n{frame['visual']}"
            if frame["events"]:
                msg += f"\n{'='*20}\n" + "\n".join(frame["events"])
            msg += f"\n{'='*20}\n{frame['commentary']}"
            try:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
            except Exception as exc:
                logger.exception(f"发送赛博竞速过程消息失败 group_id={group_id}: {exc}")
            await asyncio.sleep(STORY_DELAY_SECONDS)

    service.settle_round(race["round_id"])
    active_races.pop(group_id, None)

    rank_text = "\n".join(
        f"{'🥇' if index == 0 else '🥈' if index == 1 else '🥉' if index == 2 else '4.'} "
        f"{horses[horse_index]['emoji']} {horses[horse_index]['name']}"
        for index, (horse_index, _position) in enumerate(results)
    )
    winner_announce = random.choice(WINNER_ANNOUNCE)
    result_comment = (
        random.choice(BET_WIN_MESSAGES)
        if winners
        else "（摇头）竟然没有人选中...本猫也很意外..."
    )
    winner_text = "\n".join(winners) if winners else "（无人选中）"
    loser_text = "\n".join(losers) if losers else "（无）"
    poem = f"竞速场上尘飞扬，\n{winner['name']}今日最风光。\n有人欢喜有人愁，\n结果不过一场梦~"

    if bot is not None:
        try:
            await bot.send_group_msg(
                group_id=int(group_id),
                message=f"""🏇 比赛结束！🏇
{'='*20}
{winner_announce}
🏆 {winner['emoji']} {winner['name']}！
{'='*20}
{rank_text}
{'='*20}
{result_comment}
{'='*20}
🏆 得分者：
{winner_text}

📉 暂落后者：
{loser_text}
{'='*20}
『{poem}』
{'='*20}
输入 /赛博竞速 开始新一场！""",
            )
        except Exception as exc:
            logger.exception(f"发送赛博竞速结算消息失败 group_id={group_id}: {exc}")

# 取消比赛
cancel_race = on_command("取消竞速", rule=FEATURE_RULE, priority=5, block=True)

@cancel_race.handle()
async def handle_cancel_race(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await cancel_race.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_races:
        await cancel_race.finish("（摊手）当前没有赛博竞速！")
    
    race = active_races[group_id]
    
    if race["started"]:
        await cancel_race.finish("（摇头）比赛已经开始了，没法取消！")
    
    _round_service().refund_round(race["round_id"], reason="user_cancelled")
    active_races.pop(group_id, None)
    
    await cancel_race.finish(
        f"🏇 赛博竞速已取消，积分已退还~\n"
        f"{'='*20}\n"
        f"（收起旗子）没事没事，改日再来~"
    )




