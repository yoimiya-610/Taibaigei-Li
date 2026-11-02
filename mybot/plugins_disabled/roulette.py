from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="legacy_roulette",
    name="转盘挑战",
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
    next_local_midnight_timestamp,
    register_recovery_adapter,
)
from mybot.plugins.rate_limit import check_game_limit, get_limit_message
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)
FEATURE_KEY = "legacy_roulette"
SOLO_GAME_TYPE = "roulette_solo"
PVP_GAME_TYPE = "roulette_pvp"
MAX_BET = 100
SOLO_SAFE_BONUS_RATE = 0.15
PVP_POOL_PAYOUT_RATE = 0.95
HELP_ITEMS = (
    HelpItem("小游戏", "/转盘挑战 金额 - 转盘挑战", 60),
)
COMMAND_ALIASES = (
    "转盘挑战",
    "转盘",
    "开转盘",
    "加入转盘",
    "开始转盘",
    "转一轮",
    "揭结果",
    "取消转盘",
)


async def _feature_enabled(event: MessageEvent) -> bool:
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    return is_feature_enabled(FEATURE_KEY, group_id)


FEATURE_RULE = Rule(_feature_enabled)

# 冷却时间
cooldown = {}
COOLDOWN_TIME = 5

# 转盘挑战多人模式 {group_id: {"players": [], "bet": int, "current": int, "bullet": int}}
pvp_games = {}


def _round_service() -> PaidRoundService:
    return PaidRoundService()


def _hydrate_pvp_round(round_record: dict) -> dict:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    known_users = {player["user_id"] for player in game.setdefault("players", [])}
    for participant in round_record.get("participants", {}).values():
        if participant.get("state") not in {"active", "settled"}:
            continue
        metadata = participant.get("metadata", {})
        if metadata.get("role") != "player" or participant["user_id"] in known_users:
            continue
        game["players"].append(
            {
                "user_id": participant["user_id"],
                "nickname": metadata["nickname"],
                "alive": bool(metadata.get("alive", True)),
            }
        )
    return game


def _restore_pvp_round(round_record: dict, service: PaidRoundService) -> None:
    pvp_games[round_record["group_id"]] = _hydrate_pvp_round(round_record)


def _pvp_round_is_loaded(round_record: dict) -> bool:
    return pvp_games.get(round_record["group_id"], {}).get("round_id") == round_record["round_id"]


def _discard_pvp_round(round_record: dict, service: PaidRoundService) -> None:
    if _pvp_round_is_loaded(round_record):
        pvp_games.pop(round_record["group_id"], None)


def _expire_pvp_round(round_record: dict, service: PaidRoundService) -> None:
    _discard_pvp_round(round_record, service)
    service.refund_round(round_record["round_id"], reason="room_deadline_expired")


register_recovery_adapter(
    PVP_GAME_TYPE,
    restore=_restore_pvp_round,
    is_loaded=_pvp_round_is_loaded,
    discard=_discard_pvp_round,
    on_due=_expire_pvp_round,
)

# 单人揭结果文案
SOLO_PULL_MESSAGES = [
    "（转动转盘）咔哒咔哒...命运的齿轮开始转动~",
    "（推墨镜）进退一瞬间，你准备好了吗？",
    "（晃酒壶）来，先干一杯壮胆酒~",
    "（抬眉）有胆识，本猫欣赏你~",
]

# 单人存活文案
SOLO_SURVIVE_MESSAGES = [
    "（鼓掌）运气不错！今天不是你的退场时刻~",
    "（竖大拇指）稳住真好，对吧？",
    "（抛媚眼）还稳着？要不要让本猫亲亲压压惊？",
    "（举杯）稳住一轮，必有后福！干杯！",
    "（拍肩）淡定，本猫就知道你稳得住~",
]

# 单人触发提示牌文案
SOLO_DEATH_MESSAGES = [
    "（捂眼）啊！提示一出...开玩笑的，但积分是真没了~",
    "（叹气）命运无常啊...你的积分，本猫会替你好好保管的~",
    "（假装哭泣）呜呜呜，本猫痛失一位金主...不对，是朋友！",
    "（递花）且慢且慢，本轮积分已完成结算~",
    "（摇头）闯关这种事，本猫劝你以后还是少玩...",
]

# 多人开场文案
PVP_START_MESSAGES = [
    "（装填提示牌）咔哒...六个转盘，一颗提示牌，谁是幸运儿？",
    "（推墨镜）勇士们，准备好了吗？这是一场进退游戏~",
    "（晃酒壶）来来来，闯关之前先喝一杯！",
    "（抬眉）有胆量参加转盘挑战？本猫敬你是条好汉！",
]

# 多人加入文案
PVP_JOIN_MESSAGES = [
    "（点头）又一位勇士！本猫看好你~",
    "（抛媚眼）哟，胆子大的又多了一个~",
    "（举杯）欢迎入局！祝你好运~",
    "（拍肩）勇气可嘉！希望你不是第一个退场的~",
]

# 多人揭结果存活文案
PVP_SURVIVE_MESSAGES = [
    "（擦汗）空格！命真大！",
    "（鼓掌）活下来了！继续~",
    "（点头）还没轮到你，继续苟着~",
    "（笑）好运今日还在你身边~",
]

# 多人触发提示牌文案
PVP_DEATH_MESSAGES = [
    "（捂眼）叮！退场一位！",
    "（叹气）又一位勇士退场了...",
    "（收声）这一轮到此为止，积分按规则结算~",
    "（摇头）早知今日，何必当初~",
]

# 多人胜利文案
PVP_WIN_MESSAGES = [
    "（撒花）最后的幸存者！王者诞生！",
    "（鼓掌）稳住一轮，拿下本轮！太强了！",
    "（举杯）恭喜恭喜！今晚本猫请你喝酒！",
    "（抛媚眼）得分者你好，要不要和本猫交个朋友？",
]

# ========== 转盘挑战：单人模式 ==========
solo_roulette = on_command("转盘", rule=FEATURE_RULE, priority=5, block=True)

@solo_roulette.handle()
async def handle_solo_roulette(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await solo_roulette.finish("（摇头）转盘挑战要在群里玩才刺激~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    cd_key = f"{group_id}_{user_id}"
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"单人转盘获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 检查冷却
    now = time.time()
    if cd_key in cooldown and now - cooldown[cd_key] < COOLDOWN_TIME:
        remaining = int(COOLDOWN_TIME - (now - cooldown[cd_key]))
        await solo_roulette.finish(f"（按住你的手）冷静冷静，{remaining}秒后再来~")
    
    # 解析金额
    bet_str = args.extract_plain_text().strip()
    
    if not bet_str:
        await solo_roulette.finish(
            f"🎲 李太白给·转盘挑战 🎲\n"
            f"{'='*20}\n"
            f"（转动转盘）想不想来一轮挑战？\n"
            f"{'='*20}\n"
            f"【单人模式】\n"
            f"/转盘 金额\n"
            f"• 6个转盘，1颗提示牌\n"
            f"• 存活(5/6)：+0.15倍选择\n"
            f"• 触发提示牌(1/6)：本轮未得分\n"
            f"{'='*20}\n"
            f"【多人对决】\n"
            f"/转盘挑战 金额 - 开场\n"
            f"/加入转盘 - 加入\n"
            f"/开始转盘 - 人齐后开始\n"
            f"/转一轮 - 轮到自己时揭结果\n"
            f"{'='*20}\n"
            f"单次最高 {MAX_BET} 积分\n"
            f"『进退一念间，\n结果弹指间。\n敢问阁下否，\n有胆来试试？』"
        )
    
    try:
        bet = int(bet_str)
        if bet <= 0:
            raise ValueError
    except ValueError:
        await solo_roulette.finish("（敲你头）请输入正确的数字！")
    
    if bet > 100:
        await solo_roulette.finish("（摇手指）单次最多100积分！挑战有度，但要适度~")

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await solo_roulette.finish(get_limit_message(result))
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet:
        await solo_roulette.finish(f"（摇头）积分不够...你只有 {points_info['current']} 积分")
    
    pull_msg = random.choice(SOLO_PULL_MESSAGES)
    
    # 转转盘 1/6 概率触发提示牌
    bullet = random.randint(1, 6)
    shot = random.randint(1, 6)
    survived = bullet != shot
    win = int(bet * SOLO_SAFE_BONUS_RATE) if survived else 0
    total_return = bet + win if survived else 0
    service = _round_service()
    round_id = new_round_id(SOLO_GAME_TYPE)
    service.create_round(
        round_id=round_id,
        game_type=SOLO_GAME_TYPE,
        mode="instant",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_POINTS,
        feature_key=FEATURE_KEY,
        payload={"bullet": bullet, "shot": shot, "nickname": nickname, "bet": bet},
        result={"bullet": bullet, "shot": shot, "survived": survived},
        participants=[
            {
                "user_id": user_id,
                "amount": bet,
                "payout_amount": total_return,
            }
        ],
    )
    charge = service.freeze_participant(round_id, user_id)
    if not charge["ok"]:
        service.refund_round(round_id, reason="insufficient_balance")
        await solo_roulette.finish(f"（摇头）积分不够...你只有 {charge['balance']} 积分")
    service.settle_round(round_id)
    cooldown[cd_key] = now
    
    if not survived:
        # 触发提示牌
        new_points = get_points(user_id, group_id)
        comment = random.choice(SOLO_DEATH_MESSAGES)
        poem = f"一声提示响魂归西，\n{nickname}积分化飞灰。\n早知今日闯关苦，\n不如当初去签到~"
        
        await solo_roulette.finish(
            f"🎲 转盘挑战·单人模式 🎲\n"
            f"{'='*20}\n"
            f"{pull_msg}\n"
            f"{'='*20}\n"
            f"（扣动扳机）\n"
            f"✨ 叮！！！\n"
            f"{'='*20}\n"
            f"{comment}\n"
            f"{'='*20}\n"
            f"『{poem}』\n"
            f"{'='*20}\n"
            f"本局：-{bet} 积分\n"
            f"余额：{new_points['current']} 积分"
        )
    else:
        # 存活，获得0.15倍奖励
        new_points = get_points(user_id, group_id)
        
        comment = random.choice(SOLO_SURVIVE_MESSAGES)
        poem = f"空格一声响叮当，\n{nickname}今日命真长。\n小有收获一笔心欢畅，\n改日再来又何妨~"
        
        await solo_roulette.finish(
            f"🎲 转盘挑战·单人模式 🎲\n"
            f"{'='*20}\n"
            f"{pull_msg}\n"
            f"{'='*20}\n"
            f"（扣动扳机）\n"
            f"💨 咔哒...空格！\n"
            f"{'='*20}\n"
            f"{comment}\n"
            f"{'='*20}\n"
            f"『{poem}』\n"
            f"{'='*20}\n"
            f"本局：+{win} 积分\n"
            f"余额：{new_points['current']} 积分"
        )

# ========== 转盘挑战：多人模式 ==========

# 开启转盘挑战
start_pvp = on_command("转盘挑战", aliases={"开转盘"}, rule=FEATURE_RULE, priority=5, block=True)

@start_pvp.handle()
async def handle_start_pvp(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await start_pvp.finish("（摇头）转盘挑战要在群里玩~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 检查是否已有游戏
    if group_id in pvp_games:
        game = pvp_games[group_id]
        players_text = "、".join([p["nickname"] for p in game["players"]])
        await start_pvp.finish(
            f"（敲桌子）已经有转盘挑战在等人了！\n"
            f"{'='*20}\n"
            f"参与者：{players_text}\n"
            f"选择：{game['bet']} 积分\n"
            f"{'='*20}\n"
            f"/加入转盘 - 加入游戏\n"
            f"/开始转盘 - 开始对决"
        )
    
    # 解析金额
    bet_str = args.extract_plain_text().strip()
    
    if not bet_str:
        await start_pvp.finish(
            f"🎲 李太白给·转盘挑战 🎲\n"
            f"{'='*20}\n"
            f"用法：/转盘挑战 金额\n"
            f"例如：/转盘挑战 30\n"
            f"{'='*20}\n"
            f"规则：\n"
            f"• 2-6人参与\n"
            f"• 轮流转一轮\n"
            f"• 触发提示牌者出局\n"
            f"• 每次有人触发提示牌后重新装弹\n"
            f"• 最后存活者获得95%积分池\n"
            f"{'='*20}\n"
            f"单次最高 {MAX_BET} 积分"
        )
    
    try:
        bet = int(bet_str)
        if bet <= 0:
            raise ValueError
    except ValueError:
        await start_pvp.finish("（敲你头）请输入正确的数字！")
    
    if bet > 100:
        await start_pvp.finish("（摇手指）单次最多100积分！")

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await start_pvp.finish(get_limit_message(result))
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"转盘挑战创建获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet:
        await start_pvp.finish(f"（摇头）积分不够！你只有 {points_info['current']} 积分")
    
    start_msg = random.choice(PVP_START_MESSAGES)
    
    # 创建游戏
    game = {
        "players": [{"user_id": user_id, "nickname": nickname, "alive": True}],
        "bet": bet,
        "current": 0,
        "bullet": random.randint(1, 6),
        "chamber": 0,
        "started": False
    }
    service = _round_service()
    round_id = new_round_id(PVP_GAME_TYPE)
    game["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=PVP_GAME_TYPE,
        mode="multiplayer",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_POINTS,
        feature_key=FEATURE_KEY,
        payload=game,
        participants=[
            {
                "user_id": user_id,
                "amount": bet,
                "metadata": {"role": "player", "nickname": nickname, "alive": True},
            }
        ],
        deadline_at=next_local_midnight_timestamp(),
    )
    charge = service.freeze_participant(round_id, user_id)
    if not charge["ok"]:
        service.refund_round(round_id, reason="insufficient_balance")
        await start_pvp.finish(f"（摇头）积分不够！你只有 {charge['balance']} 积分")
    pvp_games[group_id] = game
    
    await start_pvp.finish(
        f"🎲 李太白给·转盘挑战 🎲\n"
        f"{'='*20}\n"
        f"📢 {nickname} 发起了转盘挑战！\n"
        f"💰 选择：{bet} 积分\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"/加入转盘 - 加入（需{bet}积分）\n"
        f"/开始转盘 - 人齐后开始（2-6人）\n"
        f"/取消转盘 - 取消游戏\n"
        f"{'='*20}\n"
        f"『六中藏一弹，\n进退轮流转。\n敢问诸君否，\n有胆来一战？』"
    )

# 加入转盘
join_pvp = on_command("加入转盘", rule=FEATURE_RULE, priority=5, block=True)

@join_pvp.handle()
async def handle_join_pvp(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await join_pvp.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in pvp_games:
        await join_pvp.finish("（摊手）当前没有转盘挑战！输入 /转盘挑战 金额 开一局？")
    
    game = pvp_games[group_id]
    
    if game["started"]:
        await join_pvp.finish("（摇头）游戏已经开始了，下次早点来~")
    
    # 检查是否已加入
    if any(p["user_id"] == user_id for p in game["players"]):
        await join_pvp.finish("（戳你）你已经在游戏里了！")
    
    # 检查人数
    if len(game["players"]) >= 6:
        await join_pvp.finish("（摇头）人满了！最多6人~")
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"转盘挑战加入获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    bet = game["bet"]

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await join_pvp.finish(get_limit_message(result))
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet:
        await join_pvp.finish(f"（摇头）积分不够！需要 {bet} 积分，你只有 {points_info['current']} 积分")
    
    service = _round_service()
    service.add_participant(
        game["round_id"],
        participant_id=user_id,
        user_id=user_id,
        amount=bet,
        metadata={"role": "player", "nickname": nickname, "alive": True},
    )
    charge = service.freeze_participant(game["round_id"], user_id)
    if not charge["ok"]:
        await join_pvp.finish(
            f"（摇头）积分不够！需要 {bet} 积分，你只有 {charge['balance']} 积分"
        )

    # 加入游戏并在确认消息前持久化。
    game["players"].append({"user_id": user_id, "nickname": nickname, "alive": True})
    service.update_payload(game["round_id"], game)
    
    players_text = "、".join([p["nickname"] for p in game["players"]])
    join_msg = random.choice(PVP_JOIN_MESSAGES)
    
    await join_pvp.finish(
        f"✅ {nickname} 加入了转盘挑战！\n"
        f"{join_msg}\n"
        f"{'='*20}\n"
        f"当前玩家（{len(game['players'])}/6）：\n"
        f"{players_text}\n"
        f"{'='*20}\n"
        f"/开始转盘 - 开始对决\n"
        f"/加入转盘 - 继续加入"
    )

# 开始转盘挑战
begin_pvp = on_command("开始转盘", rule=FEATURE_RULE, priority=5, block=True)

@begin_pvp.handle()
async def handle_begin_pvp(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await begin_pvp.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in pvp_games:
        await begin_pvp.finish("（摊手）当前没有转盘挑战！")
    
    game = pvp_games[group_id]
    
    if game["started"]:
        await begin_pvp.finish("（指向场上）游戏已经开始了！")
    
    if len(game["players"]) < 2:
        await begin_pvp.finish("（摇头）至少需要2人才能开始！")
    
    # 开始游戏
    game["started"] = True
    game["current"] = 0
    game["bullet"] = random.randint(1, 6)
    game["chamber"] = 0
    
    # 随机打乱顺序
    random.shuffle(game["players"])
    _round_service().update_payload(game["round_id"], game)
    
    first_player = game["players"][0]
    players_order = " → ".join([p["nickname"] for p in game["players"]])
    total_pool = game["bet"] * len(game["players"])
    
    await begin_pvp.finish(
        f"🎲 转盘挑战开始！🎲\n"
        f"{'='*20}\n"
        f"（转动转盘）咔哒咔哒...\n"
        f"{'='*20}\n"
        f"出场顺序：\n"
        f"{players_order}\n"
        f"{'='*20}\n"
        f"💰 活动积分：{total_pool} 积分\n"
        f"{'='*20}\n"
        f"🎯 请 {first_player['nickname']} 转一轮！\n"
        f"输入 /转一轮"
    )

# 转一轮
pull_trigger = on_command("转一轮", aliases={"揭结果"}, rule=FEATURE_RULE, priority=5, block=True)

@pull_trigger.handle()
async def handle_pull_trigger(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await pull_trigger.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in pvp_games:
        await pull_trigger.finish("（摊手）当前没有转盘挑战！")
    
    game = pvp_games[group_id]
    
    if not game["started"]:
        await pull_trigger.finish("（摇头）游戏还没开始！输入 /开始转盘")
    
    # 获取存活玩家
    alive_players = [p for p in game["players"] if p["alive"]]
    
    if len(alive_players) <= 1:
        await pull_trigger.finish("（摊手）游戏已经结束了！")
    
    # 检查是否轮到该玩家
    current_player = alive_players[game["current"] % len(alive_players)]
    
    if current_player["user_id"] != user_id:
        await pull_trigger.finish(f"（敲你头）还没轮到你！现在是 {current_player['nickname']} 的回合~")
    
    # 转一轮
    game["chamber"] += 1
    
    if game["chamber"] == game["bullet"]:
        # 触发提示牌
        current_player["alive"] = False
        death_msg = random.choice(PVP_DEATH_MESSAGES)
        
        # 检查剩余存活人数
        alive_players = [p for p in game["players"] if p["alive"]]
        
        if len(alive_players) == 1:
            # 游戏结束，最后存活者获胜
            winner = alive_players[0]
            total_pool = game["bet"] * len(game["players"])
            payout_pool = int(total_pool * PVP_POOL_PAYOUT_RATE)
            service = _round_service()
            service.prepare_settlement(
                game["round_id"],
                result={
                    "reason": "last_survivor",
                    "winner_id": winner["user_id"],
                    "players": game["players"],
                },
                payouts={winner["user_id"]: payout_pool},
            )
            service.settle_round(game["round_id"])
            
            win_msg = random.choice(PVP_WIN_MESSAGES)
            poem = f"转盘挑战定结果，\n{winner['nickname']}笑到最后真英雄。\n拿下本轮积分心欢喜，\n改日再来战群雄~"
            
            pvp_games.pop(group_id, None)
            
            await pull_trigger.finish(
                f"🎲 转盘挑战结束！🎲\n"
                f"{'='*20}\n"
                f"✨ 叮！！！\n"
                f"{current_player['nickname']} 退场了...\n"
                f"{'='*20}\n"
                f"{win_msg}\n"
                f"🏆 胜者：{winner['nickname']}！\n"
                f"💰 获得 {payout_pool} 积分！\n"
                f"{'='*20}\n"
                f"『{poem}』"
            )
        else:
            # 游戏继续，重新装弹
            game["bullet"] = random.randint(1, 6)
            game["chamber"] = 0
            game["current"] = 0
            _round_service().update_payload(game["round_id"], game)
            
            next_player = alive_players[0]
            alive_names = "、".join([p["nickname"] for p in alive_players])
            
            await pull_trigger.finish(
                f"🎲 转盘挑战 🎲\n"
                f"{'='*20}\n"
                f"✨ 叮！！！\n"
                f"{current_player['nickname']} 退场了...\n"
                f"{'='*20}\n"
                f"{death_msg}\n"
                f"{'='*20}\n"
                f"（重新装弹）咔哒...\n"
                f"存活：{alive_names}\n"
                f"{'='*20}\n"
                f"🎯 请 {next_player['nickname']} 转一轮！"
            )
    else:
        # 空格
        game["current"] += 1
        _round_service().update_payload(game["round_id"], game)
        alive_players = [p for p in game["players"] if p["alive"]]
        next_player = alive_players[game["current"] % len(alive_players)]
        
        survive_msg = random.choice(PVP_SURVIVE_MESSAGES)
        
        await pull_trigger.finish(
            f"🎲 转盘挑战 🎲\n"
            f"{'='*20}\n"
            f"💨 咔哒...空格！\n"
            f"{current_player['nickname']} 活下来了！\n"
            f"{'='*20}\n"
            f"{survive_msg}\n"
            f"{'='*20}\n"
            f"🎯 请 {next_player['nickname']} 转一轮！"
        )

# 取消转盘
cancel_pvp = on_command("取消转盘", rule=FEATURE_RULE, priority=5, block=True)

@cancel_pvp.handle()
async def handle_cancel_pvp(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await cancel_pvp.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in pvp_games:
        await cancel_pvp.finish("（摊手）当前没有转盘挑战！")
    
    game = pvp_games[group_id]
    
    if game["started"]:
        await cancel_pvp.finish("（摇头）游戏已经开始了，没法取消！")
    
    _round_service().refund_round(game["round_id"], reason="user_cancelled")
    pvp_games.pop(group_id, None)
    
    await cancel_pvp.finish(
        f"🎲 转盘挑战已取消，积分已退还~\n"
        f"{'='*20}\n"
        f"（收起提示牌）没事没事，开心比积分重要~"
    )




