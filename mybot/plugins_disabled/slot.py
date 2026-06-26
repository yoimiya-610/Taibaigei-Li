import random
import time
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from nonebot.rule import Rule
from common.feature_flags import is_feature_enabled
from common.help_registry import HelpItem
from plugins.points import get_points, spend_points, add_points
from plugins.rate_limit import check_game_limit, get_limit_message
from common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)
FEATURE_KEY = "legacy_slot"
HELP_ITEMS = (
    HelpItem("小游戏", "/图案转盘 金额 - 图案转盘", 20),
)
COMMAND_ALIASES = ("图案转盘", "转图案", "slot")


async def _feature_enabled() -> bool:
    return is_feature_enabled(FEATURE_KEY)


FEATURE_RULE = Rule(_feature_enabled)

# 冷却时间记录
cooldown = {}
COOLDOWN_TIME = 3

# 图案转盘符号及权重（总200）
SYMBOLS = [
    ("💎", 1),    # 钻石 - 0.5%
    ("7️⃣", 2),    # 7 - 1%
    ("⭐", 4),    # 星星 - 2%
    ("🔔", 8),    # 铃铛 - 4%
    ("🍇", 15),   # 葡萄 - 7.5%
    ("🍊", 25),   # 橙子 - 12.5%
    ("🍋", 45),   # 柠檬 - 22.5%
    ("🍒", 100),  # 樱桃 - 50%
]

# 三同计分规则（期望约0.47）
PAYOUTS = {
    "💎": 200,
    "7️⃣": 80,
    "⭐": 50,
    "🔔": 30,
    "🍇": 18,
    "🍊": 10,
    "🍋": 6,
    "🍒": 3,
}

# 两同计分规则（返还倍数）
TWO_SAME_PAYOUTS = {
    "🍒": 1.3,   # 两樱桃返还1.3倍（期望贡献0.49）
}

# 拉杆文案
PULL_MESSAGES = [
    "（推墨镜）让本猫看看今日谁是欧皇~",
    "（晃酒壶）命运的齿轮开始转动...",
    "（抚须）且看这机缘造化~",
    "（甩袖）转吧转吧，小转盘~",
    "（扇扇子）来，让本猫见证奇迹~",
]

# 超高分文案（50倍以上）
JACKPOT_MESSAGES = [
    "（墨镜碎裂）我的天！这是什么神仙运气！？",
    "（酒壶落地）本猫活了这么久，头一次见到这种欧气！",
    "（跪下）欧皇陛下！请受本猫一拜！求沾点欧气！",
    "（激动）天选之人！请问阁下还缺跟班吗！？",
]

# 高分文案（10倍以上）
BIG_WIN_MESSAGES = [
    "（鼓掌）厉害厉害！今日你就是这游戏场最靓的仔！",
    "（竖大拇指）好运爆棚！本猫都有点嫉妒了~",
    "（抛媚眼）得分这么多，要不要请本猫喝一杯庆祝？",
    "（点头）运气可以啊，今晚怕是要添彩了~",
]

# 小奖文案（三同小奖）
SMALL_WIN_MESSAGES = [
    "（点头）不错不错，小有收获~",
    "（笑）虽然不多，但也是添彩了~",
    "（拍肩）运气还行，再接再厉！",
    "（举杯）小有收获一笔，值得庆祝~",
]

# 安慰分文案（两同）
CONSOLATION_MESSAGES = [
    "（扇扇子）两个樱桃，小有收获一点~",
    "（点头）差一点就三连了，返你一点安慰~",
    "（笑）樱桃成双，也算有缘~",
    "（拍肩）虽然没三连，但也不亏~",
]

# 没达成文案
LOSE_MESSAGES = [
    "（摇头）可惜可惜...下次一定~",
    "（叹气）欧气不足，建议回去多签到攒人品~",
    "（递茶）别难过，喝杯茶消消火~",
    "（扇扇子）胜败乃兵家常事，振作起来！",
    "（假装心疼）暂落后？没关系，本猫不嫌弃你~",
    "（拍拍你）天将降大任于斯人也，必先苦其积分~",
    "（安慰）失分是为了让你更珍惜下次得分的时刻~",
]

# 积分不足文案
NO_POINTS_MESSAGES = [
    "（摇头）囊中羞涩啊...你只有 {points} 积分，先去签到吧~",
    "（叹气）穷也没关系，本猫不嫌弃~ 但机器是真的拉不了...",
    "（指向门口）只有 {points} 积分？去签到攒点再来，本猫等你~",
]

def spin():
    """转动图案转盘，返回三个符号"""
    symbols = [s[0] for s in SYMBOLS]
    weights = [s[1] for s in SYMBOLS]
    return random.choices(symbols, weights=weights, k=3)

def count_symbols(result):
    """统计每个符号出现次数"""
    counts = {}
    for s in result:
        counts[s] = counts.get(s, 0) + 1
    return counts

def calculate_win(result, bet):
    """计算获得的积分，返回 (金额, 类型)"""
    counts = count_symbols(result)
    
    # 检查三同
    for symbol, count in counts.items():
        if count == 3:
            return (bet * PAYOUTS[symbol], "triple", symbol)
    
    # 检查两同（只有樱桃有奖励）
    for symbol, count in counts.items():
        if count == 2 and symbol in TWO_SAME_PAYOUTS:
            return (int(bet * TWO_SAME_PAYOUTS[symbol]), "double", symbol)
    
    return (0, "lose", None)

slot = on_command("图案转盘", aliases={"转图案", "slot"}, rule=FEATURE_RULE, priority=5, block=True)

@slot.handle()
async def handle_slot(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await slot.finish("（摇头）图案转盘要在群里拉才热闹嘛~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    cd_key = f"{group_id}_{user_id}"
    
    try:
        user_info = await bot.get_stranger_info(user_id=int(user_id))
        nickname = user_info.get("nickname", user_id)
    except Exception as exc:
        logger.warning(f"图案转盘获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    now = time.time()
    if cd_key in cooldown and now - cooldown[cd_key] < COOLDOWN_TIME:
        remaining = int(COOLDOWN_TIME - (now - cooldown[cd_key]))
        await slot.finish(f"（按住你的手）慢点慢点，机器要冷却{remaining}秒~")
    
    bet_str = args.extract_plain_text().strip()
    
    # 游戏次数限制
    can_play, result = check_game_limit(user_id, group_id)
    if not can_play:
        await slot.finish(get_limit_message(result))
    
    if not bet_str:
        await slot.finish(
            f"🎰 李太白给·图案转盘 🎰\n"
            f"{'='*20}\n"
            f"（擦拭机器）想试试手气？\n"
            f"{'='*20}\n"
            f"用法：/图案转盘 金额\n"
            f"例如：/图案转盘 10\n"
            f"{'='*20}\n"
            f"【三同高分】\n"
            f"💎💎💎 - 200倍（传说）\n"
            f"7️⃣7️⃣7️⃣ - 80倍\n"
            f"⭐⭐⭐ - 50倍\n"
            f"🔔🔔🔔 - 30倍\n"
            f"🍇🍇🍇 - 18倍\n"
            f"🍊🍊🍊 - 10倍\n"
            f"🍋🍋🍋 - 6倍\n"
            f"🍒🍒🍒 - 3倍\n"
            f"{'='*20}\n"
            f"【安慰分】\n"
            f"🍒🍒 + 任意 - 1.3倍\n"
            f"{'='*20}\n"
            f"单次最高 100 积分\n"
            f"{'='*20}\n"
            f"『一拉一摇一念间，\n结果不过弹指间。\n文娱有度，过量伤神，\n见好就收是真言~』"
        )
    
    try:
        bet = int(bet_str)
        if bet <= 0:
            raise ValueError
    except ValueError:
        await slot.finish("（敲你头）请输入正确的数字！")
    
    if bet > 100:
        await slot.finish("（摇手指）单次最多100积分！文娱有度~")
    
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet:
        msg = random.choice(NO_POINTS_MESSAGES).format(points=points_info["current"])
        await slot.finish(msg)
    
    spend_points(user_id, group_id, bet)
    cooldown[cd_key] = now
    
    result = spin()
    win_amount, win_type, win_symbol = calculate_win(result, bet)
    
    pull_msg = random.choice(PULL_MESSAGES)
    
    if win_type == "triple":
        # 三同高分
        add_points(user_id, group_id, win_amount)
        profit = win_amount - bet
        multiplier = win_amount // bet
        
        if multiplier >= 50:
            comment = random.choice(JACKPOT_MESSAGES)
            result_text = f"🎊 超高分！！！获得 {win_amount} 积分！（+{profit}）"
            poem = f"三符连珠降神迹，\n欧气冲天破云霄。\n{nickname}今日真命好，\n本猫都想跪下叫！"
        elif multiplier >= 10:
            comment = random.choice(BIG_WIN_MESSAGES)
            result_text = f"🎉 高分！获得 {win_amount} 积分！（+{profit}）"
            poem = f"三星连珠运气旺，\n{nickname}今日财源广。\n本猫在此道声贺，\n改日请客莫要忘~"
        else:
            comment = random.choice(SMALL_WIN_MESSAGES)
            result_text = f"✨ 达成！获得 {win_amount} 积分！（+{profit}）"
            poem = f"小中一把心欢畅，\n积少成多有希望。\n见好就收是智者，\n贪心不足反遭殃~"
        
        if win_amount >= 1000:
            result_text += f"\n\n🎊 【高分播报】{nickname} 斩获 {win_amount} 积分！"
    
    elif win_type == "double":
        # 两同安慰分
        add_points(user_id, group_id, win_amount)
        profit = win_amount - bet
        comment = random.choice(CONSOLATION_MESSAGES)
        result_text = f"🍒 安慰分！获得 {win_amount} 积分！（+{profit}）"
        poem = f"两颗樱桃并蒂开，\n虽非高分也开怀。\n差一点点三连线，\n下次定能把运来~"
    
    else:
        # 没达成
        comment = random.choice(LOSE_MESSAGES)
        result_text = f"💨 没达成，本轮消耗 {bet} 积分"
        
        lose_poems = [
            f"花落去，水东流，\n图案转盘前空回首。\n结果不过云烟事，\n明日再战显身手~",
            f"时运不济莫强求，\n留得积分在手头。\n今日虽败犹可战，\n他日翻身把名留~",
            f"塞翁失马焉知非福，\n今日未成也有来日。\n{nickname}莫要垂头丧气，\n本猫请你喝杯茶~",
        ]
        poem = random.choice(lose_poems)
    
    new_points = get_points(user_id, group_id)
    
    await slot.finish(
        f"🎰 李太白给·图案转盘 🎰\n"
        f"{'='*20}\n"
        f"{pull_msg}\n"
        f"{'='*20}\n"
        f"| {result[0]} | {result[1]} | {result[2]} |\n"
        f"{'='*20}\n"
        f"{result_text}\n"
        f"{'='*20}\n"
        f"{comment}\n"
        f"{'='*20}\n"
        f"『{poem}』\n"
        f"{'='*20}\n"
        f"余额：{new_points['current']} 积分"
    )




