import random
import asyncio
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
FEATURE_KEY = "legacy_race"
MAX_BET = 100
POOL_PAYOUT_RATE = 0.95
MIN_RETURN_MULTIPLIER = 1.9
HELP_ITEMS = (
    HelpItem("小游戏", "/竞速 - 赛博竞速", 50),
)
COMMAND_ALIASES = (
    "竞速",
    "开始竞速",
    "赛博竞速",
    "选马",
    "选择竞速",
    "开跑",
    "开始跑",
    "取消竞速",
)


async def _feature_enabled() -> bool:
    return is_feature_enabled(FEATURE_KEY)


FEATURE_RULE = Rule(_feature_enabled)

# 存储进行中的比赛 {group_id: {"players": {}, "started": False, "horses": []}}
active_races = {}

# 参赛选手
HORSES = [
    {"emoji": "🐎", "name": "烈焰神驹"},
    {"emoji": "🦄", "name": "独角幻兽"},
    {"emoji": "🐢", "name": "玄武龟龟"},
    {"emoji": "🐇", "name": "闪电兔兔"},
    {"emoji": "🐌", "name": "蜗牛冲刺"},
    {"emoji": "🦊", "name": "九尾狐仙"},
]

# 随机事件
EVENTS = [
    ("{name}踩到香蕉皮滑了一跤！", -2),
    ("{name}捡到加速道具！", 3),
    ("{name}被路边的美女/帅哥吸引了...", -1),
    ("{name}突然觉醒！爆发小宇宙！", 4),
    ("{name}偷偷抄近道！", 2),
    ("{name}鞋带散了停下来系...", -2),
    ("{name}吃了神秘药丸（维生素）！", 2),
    ("{name}和观众挥手致意~", -1),
    ("{name}听到有人喊加油，冲劲十足！", 2),
    ("{name}突然肚子疼...", -3),
]

# 开赛文案
START_MESSAGES = [
    "（敲锣）诸位诸位！竞速大会即将开始！快来选择！",
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
    "（叹气）竞速取消，本猫去喝闷酒了...",
    "（收起旗子）没人捧场，本猫好寂寞...",
]

# 开始比赛
start_race = on_command("竞速", aliases={"开始竞速", "赛博竞速"}, rule=FEATURE_RULE, priority=5, block=True)

@start_race.handle()
async def handle_start_race(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await start_race.finish("（摇头）竞速要在群里才热闹嘛~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 检查是否已有比赛
    if group_id in active_races:
        race = active_races[group_id]
        if race["started"]:
            await start_race.finish("（指向赛道）比赛正在进行中！先看完这场再说~")
        else:
            horses_list = "\n".join([f"{i+1}. {h['emoji']} {h['name']}" for i, h in enumerate(race["horses"])])
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
        logger.warning(f"竞速创建获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 随机选4匹马参赛
    horses = random.sample(HORSES, 4)
    
    # 创建比赛
    active_races[group_id] = {
        "players": {},
        "started": False,
        "horses": horses,
        "starter": nickname
    }
    
    horses_list = "\n".join([f"{i+1}. {h['emoji']} {h['name']}" for i, h in enumerate(horses)])
    start_msg = random.choice(START_MESSAGES)
    
    await start_race.send(
        f"🏇 李太白给·竞速大会 🏇\n"
        f"{'='*20}\n"
        f"📢 {nickname} 发起了竞速！\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"今日参赛选手：\n\n"
        f"{horses_list}\n"
        f"{'='*20}\n"
        f"💰 30秒内参与：\n"
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
            del active_races[group_id]
            try:
                msg = random.choice(NO_BET_MESSAGES)
                await bot.send_group_msg(group_id=int(group_id), message=f"🏇 竞速取消 🏇\n{'='*20}\n{msg}")
            except Exception as exc:
                logger.exception(f"发送竞速无人参与取消消息失败 group_id={group_id}: {exc}")

# 参与
bet_horse = on_command("选马", aliases={"选择竞速"}, rule=FEATURE_RULE, priority=5, block=True)

@bet_horse.handle()
async def handle_bet_horse(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await bet_horse.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in active_races:
        await bet_horse.finish("（摊手）当前没有竞速，输入 /竞速 开一局？")
    
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
        logger.warning(f"竞速参与获取昵称失败 user_id={user_id}: {exc}")
        nickname = user_id
    
    # 检查积分
    points_info = get_points(user_id, group_id)
    if points_info["current"] < bet_amount:
        await bet_horse.finish(f"（摇头）积分不够...你只有 {points_info['current']} 积分")
    
    # 扣除积分
    spend_points(user_id, group_id, bet_amount)
    
    # 记录参与
    race["players"][user_id] = {
        "nickname": nickname,
        "horse": horse_num - 1,
        "amount": bet_amount
    }
    
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
        await go_race.finish("（摊手）当前没有竞速！")
    
    race = active_races[group_id]
    
    if race["started"]:
        await go_race.finish("（指向赛道）比赛已经在进行中了！")
    
    if not race["players"]:
        del active_races[group_id]
        await go_race.finish("（叹气）没人参与，比赛取消~")
    
    await run_race(bot, group_id)

async def run_race(bot: Bot, group_id: str):
    """进行比赛"""
    if group_id not in active_races:
        return
    
    race = active_races[group_id]
    race["started"] = True
    horses = race["horses"]
    
    # 初始化位置
    positions = [0] * len(horses)
    finish_line = 20
    
    # 发送开始消息
    start_msg = random.choice(RACE_START_MESSAGES)
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=f"🏇 比赛开始！🏇\n{'='*20}\n{start_msg}"
        )
    except Exception as exc:
        logger.exception(f"发送竞速开始消息失败 group_id={group_id}: {exc}")
    
    await asyncio.sleep(1)
    
    # 比赛进行
    event_msg = ""
    round_num = 0
    
    while max(positions) < finish_line:
        round_num += 1
        
        # 每匹马前进
        for i in range(len(horses)):
            if positions[i] < finish_line:
                # 基础速度1-4
                speed = random.randint(1, 4)
                
                # 10%概率触发随机事件
                if random.random() < 0.10:
                    event_template, effect = random.choice(EVENTS)
                    event_msg = event_template.format(name=horses[i]["name"])
                    speed = max(0, speed + effect)
                
                positions[i] = min(positions[i] + speed, finish_line)
        
        # 生成赛道显示
        track_display = []
        for i, h in enumerate(horses):
            progress = int(positions[i] / finish_line * 15)
            track = "=" * progress + h["emoji"] + "-" * (15 - progress)
            track_display.append(f"{h['name'][:4]}|{track}|")
        
        race_visual = "\n".join(track_display)
        
        # 发送进度
        msg = f"🏇 第{round_num}轮 🏇\n{'='*20}\n{race_visual}"
        if event_msg:
            msg += f"\n{'='*20}\n📢 {event_msg}"
            event_msg = ""
        
        try:
            await bot.send_group_msg(group_id=int(group_id), message=msg)
        except Exception as exc:
            logger.exception(f"发送竞速过程消息失败 group_id={group_id}: {exc}")
        
        await asyncio.sleep(2)
    
    # 确定名次
    results = sorted(enumerate(positions), key=lambda x: x[1], reverse=True)
    winner_idx = results[0][0]
    winner = horses[winner_idx]
    
    # 结算
    winners = []
    losers = []
    total_pool = sum(p["amount"] for p in race["players"].values())
    winner_pool = sum(p["amount"] for p in race["players"].values() if p["horse"] == winner_idx)
    
    for user_id, bet_info in race["players"].items():
        nickname = bet_info["nickname"]
        bet_horse_idx = bet_info["horse"]
        bet_amount = bet_info["amount"]
        
        if bet_horse_idx == winner_idx:
            # 得分了，按比例分奖池（统一压到略低于 1 的均值）
            if winner_pool > 0:
                win_ratio = bet_amount / winner_pool
                win_amount = max(
                    int(total_pool * win_ratio * POOL_PAYOUT_RATE),
                    int(bet_amount * MIN_RETURN_MULTIPLIER),
                )
            else:
                win_amount = int(bet_amount * MIN_RETURN_MULTIPLIER)
            
            add_points(user_id, group_id, win_amount)
            profit = win_amount - bet_amount
            winners.append(f"🎉 {nickname}：+{profit}")
        else:
            losers.append(f"💀 {nickname}：-{bet_amount}")
    
    # 名次显示
    rank_text = "\n".join([
        f"{'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else '4.'} {horses[idx]['emoji']} {horses[idx]['name']}"
        for i, (idx, pos) in enumerate(results)
    ])
    
    # 文案
    winner_announce = random.choice(WINNER_ANNOUNCE)
    
    if winners:
        result_comment = random.choice(BET_WIN_MESSAGES)
    else:
        result_comment = "（摇头）竟然没有人选中...本猫也很意外..."
    
    winner_text = "\n".join(winners) if winners else "（无人选中）"
    loser_text = "\n".join(losers) if losers else "（无）"
    
    # 删除比赛
    del active_races[group_id]
    
    # 结尾打油诗
    poem = f"竞速场上尘飞扬，\n{winner['name']}今日最风光。\n有人欢喜有人愁，\n结果不过一场梦~"
    
    # 发送结果
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
输入 /竞速 开始新一场！"""
        )
    except Exception as exc:
        logger.exception(f"发送竞速结算消息失败 group_id={group_id}: {exc}")

# 取消比赛
cancel_race = on_command("取消竞速", rule=FEATURE_RULE, priority=5, block=True)

@cancel_race.handle()
async def handle_cancel_race(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await cancel_race.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_races:
        await cancel_race.finish("（摊手）当前没有竞速！")
    
    race = active_races[group_id]
    
    if race["started"]:
        await cancel_race.finish("（摇头）比赛已经开始了，没法取消！")
    
    # 退还积分
    for user_id, bet_info in race["players"].items():
        add_points(user_id, group_id, bet_info["amount"])
    
    del active_races[group_id]
    
    await cancel_race.finish(
        f"🏇 竞速已取消，积分已退还~\n"
        f"{'='*20}\n"
        f"（收起旗子）没事没事，改日再来~"
    )




