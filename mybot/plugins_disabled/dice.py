from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="legacy_dice",
    name="点数方块",
    default_enabled=False,
    scope="group",
    permission_level=4,
    data_files=("data/paid_rounds.json", "data/points.json"),
    privacy_level="personal",
    backup_policy="standard",
)

import asyncio
import random
import re
import time
from typing import Any

from nonebot import get_bots, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
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
FEATURE_KEY = "legacy_dice"
GAME_TYPE = "dice"
MAX_BET = 100
BIG_SMALL_PAYOUT = 1.95
TRIPLE_PAYOUT = 34
QQ_DICE_COUNT = 3
QQ_DICE_FETCH_ATTEMPTS = 3
QQ_DICE_FETCH_DELAY_SECONDS = 0.2
HELP_ITEMS = (
    HelpItem("小游戏", "/点数方块 - 点数方块", 30),
)
COMMAND_ALIASES = (
    "点数方块",
    "点数挑战",
    "点数局",
    "开点数局",
    "选大",
    "选小",
    "选三同",
    "结算",
)


async def _feature_enabled(event: MessageEvent) -> bool:
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    return is_feature_enabled(FEATURE_KEY, group_id)


FEATURE_RULE = Rule(_feature_enabled)

# 存储进行中的点数方块 {group_id: {"bets": {user_id: {"type": str, "amount": int}}, "starter": str}}
active_games = {}
settlement_locks: dict[str, asyncio.Lock] = {}


class QQDiceResultError(RuntimeError):
    """Raised when a native QQ dice result cannot be recovered safely."""


def _round_service() -> PaidRoundService:
    return PaidRoundService()


def _hydrate_round(round_record: dict) -> dict:
    game = round_record["payload"]
    game["round_id"] = round_record["round_id"]
    bets = game.setdefault("bets", {})
    for participant in round_record.get("participants", {}).values():
        if participant.get("state") not in {"active", "settled"}:
            continue
        metadata = participant.get("metadata", {})
        if metadata.get("role") != "bet":
            continue
        bets.setdefault(
            participant["user_id"],
            {
                "type": metadata["type"],
                "amount": participant["amount"],
                "nickname": metadata["nickname"],
            },
        )
    return game


def _restore_round(round_record: dict, service: PaidRoundService) -> None:
    active_games[round_record["group_id"]] = _hydrate_round(round_record)


def _round_is_loaded(round_record: dict) -> bool:
    return active_games.get(round_record["group_id"], {}).get("round_id") == round_record["round_id"]


def _discard_round(round_record: dict, service: PaidRoundService) -> None:
    if _round_is_loaded(round_record):
        active_games.pop(round_record["group_id"], None)


def _connected_bot() -> Bot | None:
    return next(iter(get_bots().values()), None)


def _extract_message_id(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    message_id = response.get("message_id")
    if message_id is None and isinstance(response.get("data"), dict):
        message_id = response["data"].get("message_id")
    if message_id is None or not str(message_id).strip():
        return None
    return str(message_id).strip()


def _normalize_dice_result(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if 1 <= result <= 6 else None


def _extract_dice_result(value: Any) -> int | None:
    if isinstance(value, MessageSegment):
        if value.type == "dice":
            return _normalize_dice_result(value.data.get("result"))
        return None

    if isinstance(value, Message):
        for segment in value:
            result = _extract_dice_result(segment)
            if result is not None:
                return result
        return None

    if isinstance(value, dict):
        if value.get("type") == "dice" and isinstance(value.get("data"), dict):
            return _normalize_dice_result(value["data"].get("result"))
        for key in ("message", "raw_message"):
            if key in value:
                result = _extract_dice_result(value[key])
                if result is not None:
                    return result
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            result = _extract_dice_result(item)
            if result is not None:
                return result
        return None

    if isinstance(value, str):
        match = re.search(r"\[CQ:dice(?:,[^\]]*?)?result=([1-6])(?:,[^\]]*)?\]", value)
        if match:
            return int(match.group(1))
    return None


async def _read_qq_dice_result(bot: Bot, message_id: str) -> int:
    last_error: Exception | None = None
    for attempt in range(QQ_DICE_FETCH_ATTEMPTS):
        try:
            message = await bot.get_msg(message_id=message_id)
            result = _extract_dice_result(message)
            if result is not None:
                return result
        except Exception as exc:
            last_error = exc

        if attempt + 1 < QQ_DICE_FETCH_ATTEMPTS:
            await asyncio.sleep(QQ_DICE_FETCH_DELAY_SECONDS)

    error = QQDiceResultError(f"无法读取 QQ 骰子结果 message_id={message_id}")
    if last_error is not None:
        raise error from last_error
    raise error


async def _collect_qq_dice_results(
    bot: Bot,
    group_id: str,
    game: dict,
    service: PaidRoundService,
) -> list[int]:
    rolls = game.setdefault("qq_dice_rolls", [])
    if not isinstance(rolls, list) or len(rolls) > QQ_DICE_COUNT:
        raise QQDiceResultError("付费回合中的 QQ 骰子记录无效")

    for index in range(QQ_DICE_COUNT):
        if index >= len(rolls):
            try:
                response = await bot.send_group_msg(
                    group_id=int(group_id),
                    message=MessageSegment.dice(),
                )
            except Exception as exc:
                raise QQDiceResultError(f"第 {index + 1} 枚 QQ 骰子发送失败") from exc

            message_id = _extract_message_id(response)
            if message_id is None:
                raise QQDiceResultError(f"第 {index + 1} 枚 QQ 骰子未返回消息 ID")
            rolls.append({"message_id": message_id})
            service.update_payload(game["round_id"], game)

        roll = rolls[index]
        if not isinstance(roll, dict) or not str(roll.get("message_id", "")).strip():
            raise QQDiceResultError(f"第 {index + 1} 枚 QQ 骰子记录无效")

        result = _normalize_dice_result(roll.get("result"))
        if result is None:
            result = await _read_qq_dice_result(bot, str(roll["message_id"]))
            roll["result"] = result
            service.update_payload(game["round_id"], game)

    return [int(roll["result"]) for roll in rolls]


async def _notify_qq_dice_pending(
    bot: Bot,
    group_id: str,
    game: dict,
    service: PaidRoundService,
) -> None:
    if game.get("qq_dice_pending_notified"):
        return
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=(
                "（按住酒壶）骰影一时看不真切，本猫先封住此局，"
                "稍后仍按方才的原骰判定，不会重复扣分。"
            ),
        )
        game["qq_dice_pending_notified"] = True
        service.update_payload(game["round_id"], game)
    except Exception as exc:
        logger.exception(f"发送 QQ 骰子待确认提示失败 group_id={group_id}: {exc}")


async def _settle_due_round(round_record: dict, service: PaidRoundService) -> None:
    if not _round_is_loaded(round_record):
        _restore_round(round_record, service)
    await settle_game(_connected_bot(), round_record["group_id"])


register_recovery_adapter(
    GAME_TYPE,
    restore=_restore_round,
    is_loaded=_round_is_loaded,
    discard=_discard_round,
    on_due=_settle_due_round,
)

# 开场文案
START_MESSAGES = [
    "（甩袖斟酒）来来来！人生得意须尽欢，莫使金樽空对月！\n尔等速速参与，三十秒后本诗人亲自掷骰！",
    "（推墨镜）哟~又有小可爱想试试运气？\n来吧来吧，让本大爷看看谁是今日的天选之人~",
    "（摇酒壶）点数方块点数方块，命运的小方块~\n谁能得到它的青睐呢？本诗人拭目以待！",
    "（撩唐装下摆）游戏场如战场，诸位可要想清楚了~\n不过暂落后也没关系，大不了...让本诗人亲亲你作为安慰？",
]

# 参与成功文案
BET_SUCCESS = [
    "（点头）好胆识！本诗人看好你~",
    "（抛媚眼）选{bet_type}？有品位，和本诗人一样~",
    "（举杯）勇者无惧！来，先干一杯~",
    "（扇扇子）{nickname}选{bet_type}，气势不错~",
]

# 结算 - 三同文案
TRIPLE_MESSAGES = [
    "（惊得酒壶落地）我滴个乖乖！三同！全场结算！\n这是命运的号角啊！",
    "（墨镜碎裂）豹！子！本诗人也没想到！\n天意难违，天意难违啊！",
    "（抚须长叹）三星连珠，三同临门！\n此乃天象异变，诸位请受命运之裁决！",
]

# 结算 - 得分者多文案
WINNER_MESSAGES = [
    "（拍桌）今日诸位运势不错！本诗人今日也算尽兴了~",
    "（假装心痛）呜呜呜，你们都得分了，本诗人要去喝西北风了~",
    "（竖大拇指）厉害厉害！诸位英雄，改日请本诗人喝酒啊~",
    "（撩头发）得分了？很好很好~今晚要不要来本诗人房间庆祝一下？",
]

# 结算 - 暂落后者多文案  
LOSER_MESSAGES = [
    "（扇扇子）主持人小有收获，诸位承让~ 下次再来，本诗人随时奉陪~",
    "（得意地晃酒壶）哈哈哈！本诗人今晚又能加菜了！",
    "（假装安慰）暂落后不要紧，来，让本诗人抱抱你~",
    "（吟诗）胜败乃兵家常事，诸位莫要气馁~\n明日再战，说不定就能得分回本诗人的心呢~",
]

# 结算 - 平局文案
TIE_MESSAGES = [
    "（捋胡子）有暂落后有得分，正常正常~ 这就是人生啊~",
    "（喝酒）平分秋色，各有结果，妙哉妙哉~",
    "（点头）今日打成平手，诸位改日再来~",
]

# 无人参与文案
NO_BET_MESSAGES = [
    "（委屈）一个人都没有...本诗人好寂寞...",
    "（收起点数方块）没人陪本诗人玩，那本诗人去撩别的群友了~",
    "（叹气）点数方块作废~诸位是不是不爱本诗人了？",
]

# 积分不足文案
NO_POINTS_MESSAGES = [
    "（摇头）囊中羞涩啊~你只有 {points} 积分，去签到攒点再来吧~",
    "（递手帕）穷...穷也没关系，本诗人不嫌弃你~ 但点数方块是真的摇不了，先去积累一点积分吧~",
    "（心疼）哎呀，只有 {points} 积分了？要不要本诗人借你点？...开玩笑的，快去签到！",
]

# 点数方块
start_dice = on_command("点数方块", aliases={"点数挑战", "点数局", "开点数局"}, rule=FEATURE_RULE, priority=5, block=True)

@start_dice.handle()
async def handle_start_dice(bot: Bot, event: MessageEvent):
    # 私聊不支持
    if not isinstance(event, GroupMessageEvent):
        await start_dice.finish("（摇头）点数方块要在群里摇才热闹嘛~私聊多没意思~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 检查是否已有进行中的点数方块
    if group_id in active_games:
        await start_dice.finish("（敲桌子）本群已有点数方块进行中！\n要么参与，要么等着，别急~")
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"点数方块创建获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 创建点数方块
    active_games[group_id] = {
        "bets": {},
        "starter": nickname,
    }
    service = _round_service()
    round_id = new_round_id(GAME_TYPE)
    active_games[group_id]["round_id"] = round_id
    service.create_round(
        round_id=round_id,
        game_type=GAME_TYPE,
        mode="timed",
        group_id=group_id,
        creator_id=user_id,
        asset_type=ASSET_POINTS,
        feature_key=FEATURE_KEY,
        payload=active_games[group_id],
        deadline_at=time.time() + 30,
    )
    
    start_msg = random.choice(START_MESSAGES)
    
    await start_dice.send(
        f"🎲 李太白给·点数方块 🎲\n"
        f"{'='*20}\n"
        f"📢 {nickname} 开启了点数方块！\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"/选大 金额 - 试点数11-17\n"
        f"/选小 金额 - 试点数4-10\n"
        f"/选三同 金额 - 试三个相同\n"
        f"{'='*20}\n"
        f"大/小 奖励1.95倍 | 三同 奖励34倍\n"
        f"单次最高{MAX_BET}积分 | /结算 提前结算"
    )
    
    # 创建后台任务进行倒计时
    asyncio.create_task(auto_settle(bot, group_id))

async def auto_settle(bot: Bot, group_id: str):
    """30秒后自动结算"""
    await asyncio.sleep(30)
    
    # 检查点数方块是否还存在（可能已被手动结算）
    if group_id in active_games:
        await settle_game(bot, group_id)

# 选大
bet_big = on_command("选大", rule=FEATURE_RULE, priority=5, block=True)

@bet_big.handle()
async def handle_bet_big(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await bet_big.finish("（摇头）要在群里玩哦~")
    await place_bet(bot, event, "大", args)

# 选小
bet_small = on_command("选小", rule=FEATURE_RULE, priority=5, block=True)

@bet_small.handle()
async def handle_bet_small(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await bet_small.finish("（摇头）要在群里玩哦~")
    await place_bet(bot, event, "小", args)

# 选三同
bet_triple = on_command("选三同", rule=FEATURE_RULE, priority=5, block=True)

@bet_triple.handle()
async def handle_bet_triple(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await bet_triple.finish("（摇头）要在群里玩哦~")
    await place_bet(bot, event, "三同", args)

async def place_bet(bot: Bot, event: MessageEvent, bet_type: str, args: Message):
    """处理参与"""
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 检查是否有进行中的点数方块
    if group_id not in active_games:
        await bot.send(event, "（摊手）当前没有点数方块~输入 /点数方块 开一局？")
        return
    
    game = active_games[group_id]
    
    # 检查是否已经参与
    if user_id in game["bets"]:
        await bot.send(event, "（戳你脑门）你已经参与了！一人一次，不许贪心~")
        return
    
    # 解析金额
    amount_str = args.extract_plain_text().strip()
    if not amount_str:
        await bot.send(event, f"（敲你头）金额呢？格式：/选{bet_type} 50")
        return
    
    try:
        amount = int(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await bot.send(event, "（无语）请输入正确的数字！")
        return
    
    if amount > MAX_BET:
        await bot.send(event, "（摇手指）单次最多100积分！文娱有度，过量伤神~")
        return

    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await bot.send(event, get_limit_message(result))
        return
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < amount:
        msg = random.choice(NO_POINTS_MESSAGES).format(points=points_info["current"])
        await bot.send(event, msg)
        return
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"点数方块参与获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    bet_record = {
        "type": bet_type,
        "amount": amount,
        "nickname": nickname
    }
    service = _round_service()
    service.add_participant(
        game["round_id"],
        participant_id=user_id,
        user_id=user_id,
        amount=amount,
        metadata={"role": "bet", "type": bet_type, "nickname": nickname},
    )
    charge = service.freeze_participant(game["round_id"], user_id)
    if not charge["ok"]:
        await bot.send(event, random.choice(NO_POINTS_MESSAGES).format(points=charge["balance"]))
        return
    game["bets"][user_id] = bet_record
    service.update_payload(game["round_id"], game)
    
    success_msg = random.choice(BET_SUCCESS).format(nickname=nickname, bet_type=bet_type)
    await bot.send(event, f"✅ {nickname} 选【{bet_type}】{amount}积分！\n{success_msg}")

# 结算
settle = on_command("结算", rule=FEATURE_RULE, priority=5, block=True)

@settle.handle()
async def handle_settle(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await settle.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_games:
        await settle.finish("（摊手）当前没有点数方块~")
    
    await settle_game(bot, group_id)

async def settle_game(bot: Bot | None, group_id: str):
    lock = settlement_locks.setdefault(group_id, asyncio.Lock())
    async with lock:
        await _settle_game_locked(bot, group_id)


async def _settle_game_locked(bot: Bot | None, group_id: str):
    """结算点数方块"""
    if group_id not in active_games:
        return
    
    game = active_games[group_id]
    bets = game["bets"]
    
    # 没人参与
    if not bets:
        _round_service().expire_round(game["round_id"], reason="no_participants")
        active_games.pop(group_id, None)
        try:
            msg = random.choice(NO_BET_MESSAGES)
            if bot is not None:
                await bot.send_group_msg(group_id=int(group_id), message=f"🎲 点数方块结束 🎲\n{'='*20}\n{msg}")
        except Exception as exc:
            logger.exception(f"发送无人参与点数方块结束消息失败 group_id={group_id}: {exc}")
        return
    
    if bot is None:
        logger.warning(f"QQ 骰子结算等待 OneBot 连接 group_id={group_id}")
        return

    service = _round_service()
    try:
        dice1, dice2, dice3 = await _collect_qq_dice_results(bot, group_id, game, service)
    except Exception as exc:
        logger.exception(f"QQ 骰子结果尚未确认 group_id={group_id}: {exc}")
        await _notify_qq_dice_pending(bot, group_id, game, service)
        return

    total = dice1 + dice2 + dice3
    
    # 判断结果
    is_triple = (dice1 == dice2 == dice3)
    result = "三同" if is_triple else ("大" if total >= 11 else "小")
    
    # 结算
    winners = []
    losers = []
    payouts = {}
    
    for user_id, bet_info in bets.items():
        bet_type = bet_info["type"]
        amount = bet_info["amount"]
        nickname = bet_info["nickname"]
        
        # 计算结果
        if is_triple:
            # 三同全场结算，只有选三同的得分
            if bet_type == "三同":
                win_amount = int(amount * TRIPLE_PAYOUT)
                payouts[user_id] = win_amount
                winners.append(f"🎉 {nickname}：+{win_amount - amount}（选{bet_type} {amount}）")
            else:
                losers.append(f"💀 {nickname}：-{amount}（选{bet_type}）")
        else:
            # 非三同
            if bet_type == "三同":
                losers.append(f"💀 {nickname}：-{amount}（选{bet_type}）")
            elif bet_type == result:
                win_amount = int(amount * BIG_SMALL_PAYOUT)
                payouts[user_id] = win_amount
                winners.append(f"🎉 {nickname}：+{win_amount - amount}（选{bet_type} {amount}）")
            else:
                losers.append(f"💀 {nickname}：-{amount}（选{bet_type}）")
    
    service.prepare_settlement(
        game["round_id"],
        result={
            "dice": [dice1, dice2, dice3],
            "total": total,
            "result": result,
            "is_triple": is_triple,
        },
        payouts=payouts,
    )
    service.settle_round(game["round_id"])
    active_games.pop(group_id, None)
    
    # 生成结果消息
    dice_display = f"🎲 {dice1} | 🎲 {dice2} | 🎲 {dice3}"
    result_emoji = "🎰 三同！全场结算！" if is_triple else f"点数：{total}（{result}）"
    
    # 随机诗人评语
    if is_triple:
        intro = random.choice(TRIPLE_MESSAGES)
    elif len(winners) > len(losers):
        intro = random.choice(WINNER_MESSAGES)
    elif len(winners) < len(losers):
        intro = random.choice(LOSER_MESSAGES)
    else:
        intro = random.choice(TIE_MESSAGES)
    
    winners_text = "\n".join(winners) if winners else "（无）"
    losers_text = "\n".join(losers) if losers else "（无）"
    
    # 结尾打油诗
    if is_triple:
        poem = "三星连珠三同来，\n主持人全场结算笑开怀。\n选三同者添风采，\n其余诸位莫悲哀~"
    elif len(winners) > len(losers):
        poem = "今日点数方块尔等得分，\n本诗人今日也服气。\n改日再来试身手，\n看谁才是真英雄~"
    else:
        poem = "点数方块一掷定结果，\n几家欢喜几家愁。\n明日再来战一场，\n结果不过云烟中~"
    
    msg = f"""🎲 李太白给·点数方块结算 🎲
{'='*20}
{dice_display}
{result_emoji}
{'='*20}
{intro}
{'='*20}
🏆 得分者：
{winners_text}

📉 暂落后者：
{losers_text}
{'='*20}
『{poem}』
{'='*20}
输入 /点数方块 再来一局！"""
    
    try:
        if bot is not None:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
    except Exception as exc:
        logger.exception(f"发送点数方块结算消息失败 group_id={group_id}: {exc}")




