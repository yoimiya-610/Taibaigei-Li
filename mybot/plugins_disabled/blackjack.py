import random
import time
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from nonebot.rule import Rule
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.plugins.points import get_points, spend_points, add_points
from mybot.plugins.rate_limit import check_game_limit, get_limit_message
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)
FEATURE_KEY = "legacy_blackjack"
MAX_BET = 100
NORMAL_WIN_PAYOUT = 2.0
BLACKJACK_PAYOUT = 3.0
HELP_ITEMS = (
    HelpItem("小游戏", "/纸牌挑战 金额 - 纸牌点数", 40),
)
COMMAND_ALIASES = (
    "纸牌挑战",
    "牌局挑战",
    "纸牌局",
    "要牌",
    "hit",
    "停牌",
    "stand",
    "弃牌",
    "fold",
    "放弃纸牌挑战",
)


async def _feature_enabled() -> bool:
    return is_feature_enabled(FEATURE_KEY)


FEATURE_RULE = Rule(_feature_enabled)

# 存储进行中的游戏 {group_id_user_id: {"cards": [], "dealer": [], "bet": int, "status": str}}
active_games = {}

# 冷却时间
cooldown = {}
COOLDOWN_TIME = 3

# 扑克牌
CARDS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]

# 开场文案
START_MESSAGES = [
    "（洗牌）来来来，纸牌上见真章~",
    "（推墨镜）想和本猫斗牌？有胆识~",
    "（抖唐装袖子）牌桌之上，皆是缘分~",
    "（晃酒壶）酒过三巡，牌来助兴~",
]

# 发牌文案
DEAL_MESSAGES = [
    "（抽牌）命运已经写好，你敢不敢看？",
    "（甩牌）接好了~",
    "（微笑）有意思，继续~",
]

# 满点文案
BLACKJACK_MESSAGES = [
    "（墨镜碎裂）满点！你是牌王转世吗！？",
    "（拍桌）起手21！本猫今天算是开了眼了！",
    "（鼓掌）天生得分者啊你！本猫心服口服！",
]

# 玩家爆牌文案
BUST_MESSAGES = [
    "（摇头）爆了爆了...贪心不足蛇吞象啊~",
    "（叹气）过犹不及，懂这个道理吗？",
    "（收牌）可惜可惜，差一点就稳了~",
    "（递茶）别难过，喝口茶，下次保守点~",
]

# 玩家得分文案
WIN_MESSAGES = [
    "（点头）打得漂亮！本猫甘拜下风~",
    "（鼓掌）好牌技！改天请本猫喝酒啊~",
    "（竖大拇指）厉害，今天是你的主场~",
    "（撩头发）打得本猫服气，是不是该请本猫吃顿饭？",
]

# 玩家暂落后文案
LOSE_MESSAGES = [
    "（扇扇子）承让承让~本猫运气好而已~",
    "（得意）哈哈，本猫今日兴致不错~",
    "（安慰）暂落后不要紧，来，让本猫抱抱~",
    "（假装心疼）别难过嘛~分数少了也能再攒，本猫还在呢~",
]

# 平局文案
TIE_MESSAGES = [
    "（点头）平局，各退一步，下次再战~",
    "（笑）难分伯仲，你我皆是高手~",
    "（举杯）棋逢对手，将遇良才！干杯！",
]

# 主持人爆牌文案
DEALER_BUST_MESSAGES = [
    "（假装懊恼）啊！本猫爆了！你得分了你得分了！",
    "（摔牌）怎么会这样！今天出门没看黄历！",
    "（叹气）失策失策...本猫太贪心了~",
]

def create_deck():
    """创建一副牌"""
    return [(card, suit) for card in CARDS for suit in SUITS]

def card_value(card):
    """计算单张牌的点数"""
    if card in ["J", "Q", "K"]:
        return 10
    elif card == "A":
        return 11
    else:
        return int(card)

def hand_value(cards):
    """计算手牌总点数，A可以是1或11"""
    total = sum(card_value(c[0]) for c in cards)
    aces = sum(1 for c in cards if c[0] == "A")
    
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    
    return total

def format_cards(cards, hide_first=False):
    """格式化显示手牌"""
    if hide_first and len(cards) > 0:
        return f"[🂠] [{cards[1][0]}{cards[1][1]}]"
    return " ".join([f"[{c[0]}{c[1]}]" for c in cards])

def deal_card(deck):
    """发一张牌"""
    return deck.pop(random.randint(0, len(deck) - 1))

# 开始游戏
start_bj = on_command("纸牌挑战", aliases={"牌局挑战", "纸牌局"}, rule=FEATURE_RULE, priority=5, block=True)

@start_bj.handle()
async def handle_start_bj(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await start_bj.finish("（摇头）纸牌挑战要在群里才热闹嘛~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = f"{group_id}_{user_id}"
    
    # 获取昵称
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"纸牌挑战获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 检查是否已有进行中的游戏
    if game_key in active_games:
        game = active_games[game_key]
        await start_bj.finish(
            f"（敲桌子）你还有牌局没结束呢！\n"
            f"{'='*20}\n"
            f"你的手牌：{format_cards(game['cards'])}\n"
            f"点数：{hand_value(game['cards'])}\n"
            f"{'='*20}\n"
            f"/要牌 - 再来一张\n"
            f"/停牌 - 不要了"
        )
    
    # 检查冷却
    now = time.time()
    if game_key in cooldown and now - cooldown[game_key] < COOLDOWN_TIME:
        remaining = int(COOLDOWN_TIME - (now - cooldown[game_key]))
        await start_bj.finish(f"（按住你）慢点，休息{remaining}秒再来~")
        
    # 游戏次数限制
    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await start_bj.finish(get_limit_message(result))
    
    # 解析选择金额
    bet_amount = args.extract_plain_text().strip()
    
    if not bet_amount:
        await start_bj.finish(
            f"🃏 李太白给·纸牌挑战 🃏\n"
            f"{'='*20}\n"
            f"（洗牌）想来一局？\n"
            f"{'='*20}\n"
            f"用法：/纸牌挑战 金额\n"
            f"例如：/纸牌挑战 30\n"
            f"{'='*20}\n"
            f"规则：\n"
            f"• 点数尽量接近21，不能超过\n"
            f"• A可当1或11点\n"
            f"• JQK都是10点\n"
            f"• 超过纸牌点数算爆牌，直接暂落后\n"
            f"{'='*20}\n"
            f"操作：\n"
            f"/要牌 - 再来一张\n"
            f"/停牌 - 结束要牌\n"
            f"/弃牌 - 放弃（退一半）\n"
            f"{'='*20}\n"
            f"计分规则：\n"
            f"• 普通得分：奖励2倍\n"
            f"• 满点(起手21)：奖励3倍\n"
            f"• 平局归庄，不退选择\n"
            f"• 单次最高 {MAX_BET} 积分\n"
            f"{'='*20}\n"
            f"『牌中自有黄金屋，\n纸牌点数见真功。\n小心谨慎莫贪多，\n见好就收是英雄~』"
        )
    
    # 验证金额
    try:
        bet_amount = int(bet_amount)
        if bet_amount <= 0:
            raise ValueError
    except ValueError:
        await start_bj.finish("（敲你头）请输入正确的数字！")
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet_amount:
        await start_bj.finish(f"（摇头）积分不够...你只有 {points_info['current']} 积分，先去签到吧~")
    
    if bet_amount > MAX_BET:
        await start_bj.finish("（摇手指）单次最多100积分！文娱有度~")
    
    # 扣除积分
    spend_points(user_id, group_id, bet_amount)
    cooldown[game_key] = now
    
    # 创建牌组并发牌
    deck = create_deck()
    player_cards = [deal_card(deck), deal_card(deck)]
    dealer_cards = [deal_card(deck), deal_card(deck)]
    
    player_value = hand_value(player_cards)
    
    # 存储游戏状态
    active_games[game_key] = {
        "cards": player_cards,
        "dealer": dealer_cards,
        "deck": deck,
        "bet": bet_amount,
        "nickname": nickname,
        "group_id": group_id
    }
    
    start_msg = random.choice(START_MESSAGES)
    
    # 检查是否直接满点
    if player_value == 21:
        return await end_game(bot, event, game_key, "point_challenge")
    
    await start_bj.finish(
        f"🃏 李太白给·纸牌挑战 🃏\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"💰 选择：{bet_amount} 积分\n"
        f"{'='*20}\n"
        f"主持人：{format_cards(dealer_cards, hide_first=True)}\n"
        f"{'='*20}\n"
        f"你的手牌：{format_cards(player_cards)}\n"
        f"点数：{player_value}\n"
        f"{'='*20}\n"
        f"/要牌 - 再来一张\n"
        f"/停牌 - 不要了"
    )

# 要牌
hit = on_command("要牌", aliases={"hit"}, rule=FEATURE_RULE, priority=5, block=True)

@hit.handle()
async def handle_hit(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await hit.finish("（摇头）要在群里玩哦~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = f"{group_id}_{user_id}"
    
    if game_key not in active_games:
        await hit.finish("（摊手）你还没开始游戏！输入 /纸牌挑战 金额 开始~")
    
    game = active_games[game_key]
    
    # 发一张牌
    new_card = deal_card(game["deck"])
    game["cards"].append(new_card)
    
    player_value = hand_value(game["cards"])
    deal_msg = random.choice(DEAL_MESSAGES)
    
    # 检查是否爆牌
    if player_value > 21:
        return await end_game(bot, event, game_key, "bust")
    
    # 检查是否纸牌挑战
    if player_value == 21:
        return await end_game(bot, event, game_key, "stand")
    
    await hit.finish(
        f"🃏 发牌：[{new_card[0]}{new_card[1]}]\n"
        f"{'='*20}\n"
        f"{deal_msg}\n"
        f"{'='*20}\n"
        f"你的手牌：{format_cards(game['cards'])}\n"
        f"点数：{player_value}\n"
        f"{'='*20}\n"
        f"/要牌 - 再来一张\n"
        f"/停牌 - 不要了"
    )

# 停牌
stand = on_command("停牌", aliases={"stand"}, rule=FEATURE_RULE, priority=5, block=True)

@stand.handle()
async def handle_stand(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await stand.finish("（摇头）要在群里玩哦~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = f"{group_id}_{user_id}"
    
    if game_key not in active_games:
        await stand.finish("（摊手）你还没开始游戏！输入 /纸牌挑战 金额 开始~")
    
    await end_game(bot, event, game_key, "stand")

async def end_game(bot: Bot, event: MessageEvent, game_key: str, reason: str):
    """结束游戏并结算"""
    game = active_games[game_key]
    player_cards = game["cards"]
    dealer_cards = game["dealer"]
    deck = game["deck"]
    bet_amount = game["bet"]
    nickname = game["nickname"]
    group_id = game["group_id"]
    user_id = game_key.split("_", 1)[1]
    
    player_value = hand_value(player_cards)
    
    # 玩家爆牌直接暂落后
    if reason == "bust":
        del active_games[game_key]
        new_points = get_points(user_id, group_id)
        
        comment = random.choice(BUST_MESSAGES)
        poem = "贪字头上一把刀，\n要牌不慎把己伤。\n纸牌挑战需谨慎，\n见好就收才是王~"
        
        await hit.finish(
            f"🃏 李太白给·纸牌挑战 🃏\n"
            f"{'='*20}\n"
            f"你的手牌：{format_cards(player_cards)}\n"
            f"点数：{player_value} ✨ 爆牌！\n"
            f"{'='*20}\n"
            f"{comment}\n"
            f"{'='*20}\n"
            f"『{poem}』\n"
            f"{'='*20}\n"
            f"本局：-{bet_amount} 积分\n"
            f"余额：{new_points['current']} 积分"
        )
    
    # 玩家满点（起手纸牌挑战）
    is_player_point_challenge = (reason == "point_challenge" and len(player_cards) == 2)
    
    # 主持人摸牌（点数小于17必须要牌）
    while hand_value(dealer_cards) < 17:
        dealer_cards.append(deal_card(deck))
    
    dealer_value = hand_value(dealer_cards)
    is_dealer_point_challenge = (dealer_value == 21 and len(dealer_cards) == 2)
    
    # 判断结果
    win_amount = 0
    result_text = ""
    
    if is_player_point_challenge and not is_dealer_point_challenge:
        win_amount = int(bet_amount * BLACKJACK_PAYOUT)
        result_text = "🎊 满点！大胜！"
        comment = random.choice(BLACKJACK_MESSAGES)
        poem = "起手二十一，\n天意不可违。\n满点降临，\n主持人泪沾衣~"
    elif is_dealer_point_challenge and not is_player_point_challenge:
        result_text = "💀 主持人满点！"
        comment = "（得意）哈哈，本猫也是有运气的时候~"
        poem = "本猫今日运气佳，\n满点来笑哈哈。\n下次再来别气馁，\n风水轮流转到家~"
    elif dealer_value > 21:
        win_amount = int(bet_amount * NORMAL_WIN_PAYOUT)
        result_text = "🎉 主持人爆牌！你得分了！"
        comment = random.choice(DEALER_BUST_MESSAGES)
        poem = "主持人贪心要牌多，\n一不小心把自爆。\n天道好轮回，\n这次你得分了~"
    elif player_value > dealer_value:
        win_amount = int(bet_amount * NORMAL_WIN_PAYOUT)
        result_text = "🎉 点数更大！你得分了！"
        comment = random.choice(WIN_MESSAGES)
        poem = "高手过招见真章，\n点数为王你最强。\n本猫认暂落后心服口，\n改日再来讨回场~"
    elif player_value < dealer_value:
        result_text = "💀 主持人点数更大..."
        comment = random.choice(LOSE_MESSAGES)
        poem = "棋差一招暂落后半子，\n牌桌之上见高低。\n胜败乃兵家常事，\n明日再战莫心急~"
    else:
        result_text = "🤏 平手归庄，本局记作暂落后"
        comment = random.choice(TIE_MESSAGES)
        poem = "两家点数恰相当，\n旧规此局便归庄。\n若想赢回这一手，\n改日再来见锋芒~"
    
    # 发放奖励
    if win_amount > 0:
        add_points(user_id, group_id, win_amount)
    
    # 计算盈亏
    profit = win_amount - bet_amount
    if profit > 0:
        profit_text = f"+{profit}"
    elif profit < 0:
        profit_text = str(profit)
    else:
        profit_text = "±0"
    
    # 删除游戏
    del active_games[game_key]
    
    new_points = get_points(user_id, group_id)
    
    await stand.finish(
        f"🃏 李太白给·纸牌挑战 🃏\n"
        f"{'='*20}\n"
        f"你的手牌：{format_cards(player_cards)}\n"
        f"你的点数：{player_value}\n"
        f"{'='*20}\n"
        f"主持人手牌：{format_cards(dealer_cards)}\n"
        f"主持人点数：{dealer_value}{'✨ 爆牌！' if dealer_value > 21 else ''}\n"
        f"{'='*20}\n"
        f"{result_text}\n"
        f"{comment}\n"
        f"{'='*20}\n"
        f"『{poem}』\n"
        f"{'='*20}\n"
        f"本局：{profit_text} 积分\n"
        f"余额：{new_points['current']} 积分"
    )

# 弃牌
fold = on_command("弃牌", aliases={"fold", "放弃纸牌挑战"}, rule=FEATURE_RULE, priority=5, block=True)

@fold.handle()
async def handle_fold(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await fold.finish("（摇头）要在群里玩哦~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    game_key = f"{group_id}_{user_id}"
    
    if game_key not in active_games:
        await fold.finish("（摊手）你还没开始游戏！")
    
    game = active_games[game_key]
    bet_amount = game["bet"]
    nickname = game["nickname"]
    
    # 弃牌只退一半
    refund = bet_amount // 2
    if refund > 0:
        add_points(user_id, group_id, refund)
    
    del active_games[game_key]
    
    new_points = get_points(user_id, group_id)
    
    await fold.finish(
        f"🃏 {nickname} 选择弃牌\n"
        f"{'='*20}\n"
        f"（收牌）识时务者为俊杰~\n"
        f"退还一半选择：+{refund} 积分\n"
        f"{'='*20}\n"
        f"『知进退，明得失，\n弃牌也是大智慧。\n留得积分在，\n不怕没牌玩~』\n"
        f"{'='*20}\n"
        f"余额：{new_points['current']} 积分"
    )




