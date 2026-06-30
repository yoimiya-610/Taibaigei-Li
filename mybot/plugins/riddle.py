import random
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.rule import Rule
from mybot.plugins.points import add_points
from mybot.common.ai_client import prompt_completion
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("诗词文艺", "/猜谜 - 开始猜谜", 70),
)
COMMAND_ALIASES = (
    "猜谜", "出题", "猜字谜", "脑筋急转弯",
    "提示",
    "放弃", "不猜了", "结束猜谜", "公布答案",
    "当前谜题", "看题", "谜题",
)

# 存储当前进行中的猜谜 {group_id: {"riddle": str, "answer": str, "hint": str, "type": str}}
active_riddles = {}

# 已出过的谜题记录（防止短期内重复）{group_id: [answer1, answer2, ...]}
used_riddles = {}
MAX_HISTORY = 20  # 记录最近20个谜底

# API出错文案
ERROR_MESSAGES = [
    "（扶额）本猫的脑子好像宕机了...容本猫缓缓，稍后再来~",
    "（揉太阳穴）哎呀，本猫今日诗兴不佳，改日再来吧~",
    "（打哈欠）本猫困了，让本猫休息一下再说...",
    "（晃酒壶）本猫喝多了，脑子转不动了，稍等片刻~",
]

# 开局文案
START_MESSAGES = [
    "（推墨镜）来来来，考考诸位的智商~",
    "（抚须）本猫今日出一题，看谁能解~",
    "（晃酒壶）猜谜时间到！猜对有奖哦~",
    "（甩袖）诸位且听题，本猫要开始了~",
]

# 答对文案
CORRECT_MESSAGES = [
    "（鼓掌）聪明！本猫都要对你刮目相看了~",
    "（竖大拇指）厉害厉害，脑子转得够快~",
    "（抛媚眼）答对了~ 聪明的人最有魅力了~",
    "（点头）不错不错，看来不是绣花枕头~",
    "（举杯）恭喜恭喜！这智商，本猫认可~",
]

# 放弃文案
GIVEUP_MESSAGES = [
    "（叹气）罢了罢了，本猫公布答案~",
    "（摇头）想不出来？本猫就大发慈悲告诉你们~",
    "（喝酒）没人猜得出？看来这题有点难~",
]

# 提示文案
HINT_MESSAGES = [
    "（扇扇子）好吧好吧，本猫给你个提示~",
    "（推墨镜）看你们猜不出，本猫透露一点~",
    "（叹气）行行行，本猫心软，提示一下~",
]

# 谜题类型（用于让AI生成更多样的谜题）
RIDDLE_TYPES = [
    "字谜（打一个汉字）",
    "物品谜（打一个日常物品）",
    "食物谜（打一种食物或水果）",
    "动物谜（打一种动物）",
    "自然现象谜（打一种自然现象）",
    "脑筋急转弯",
]

async def generate_riddle(group_id: str) -> dict:
    """使用AI生成谜语，出错返回None"""
    # 获取已用过的谜底
    used = used_riddles.get(group_id, [])
    used_text = "、".join(used[-10:]) if used else "无"
    
    # 随机选一个类型
    riddle_type = random.choice(RIDDLE_TYPES)
    
    # 随机主题词增加多样性
    themes = ["有趣", "经典", "创意", "简单", "巧妙", "传统", "新颖", "幽默"]
    theme = random.choice(themes)
    
    prompt = f"""请生成一个{theme}的{riddle_type}。

要求：
1. 谜面要有趣、有创意，朗朗上口
2. 难度适中
3. 答案必须是明确、唯一的（一个字或一个词）
4. 答案不能是以下任何一个（已经出过了）：{used_text}

请严格按以下格式回复，不要有多余内容：
类型：{riddle_type}
谜面：xxxxx
答案：xxxxx（必须是一个明确的字或词）
提示：xxxxx"""

    content = await prompt_completion(prompt, max_tokens=200, temperature=1.0)
    if not content:
        return None

    # 解析结果
    lines = content.split("\n")
    riddle_type = ""
    riddle_text = ""
    answer = ""
    hint = ""

    for line in lines:
        line = line.strip()
        if line.startswith("类型：") or line.startswith("类型:"):
            riddle_type = line.split("：")[-1].split(":")[-1].strip()
        elif line.startswith("谜面：") or line.startswith("谜面:"):
            riddle_text = line.split("：")[-1].split(":")[-1].strip()
        elif line.startswith("答案：") or line.startswith("答案:"):
            answer = line.split("：")[-1].split(":")[-1].strip()
            # 清理答案中可能的括号说明
            if "（" in answer:
                answer = answer.split("（")[0].strip()
            if "(" in answer:
                answer = answer.split("(")[0].strip()
        elif line.startswith("提示：") or line.startswith("提示:"):
            hint = line.split("：")[-1].split(":")[-1].strip()

    # 检查答案是否已用过
    if answer and answer in used:
        return None  # 重复了，返回None让调用方重试

    if riddle_text and answer:
        return {
            "type": riddle_type or "谜语",
            "riddle": riddle_text,
            "answer": answer,
            "hint": hint or "本猫也想不出提示了..."
        }
    return None

def check_answer(user_answer: str, correct_answer: str) -> bool:
    """严格检查答案是否正确"""
    user_answer = user_answer.strip().lower()
    correct_answer = correct_answer.strip().lower()
    
    # 完全匹配
    if user_answer == correct_answer:
        return True
    
    # 去掉常见后缀再匹配
    suffixes = ["子", "儿", "头", "巴"]
    for suffix in suffixes:
        if user_answer + suffix == correct_answer:
            return True
        if user_answer == correct_answer + suffix:
            return True
        if user_answer.rstrip(suffix) == correct_answer.rstrip(suffix) and user_answer.rstrip(suffix):
            return True
    
    return False

# 出题
start_riddle = on_command("猜谜", aliases={"出题", "猜字谜", "脑筋急转弯"}, priority=5, block=True)

@start_riddle.handle()
async def handle_start_riddle(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await start_riddle.finish("（摇头）猜谜要在群里才热闹嘛~")
    
    group_id = str(event.group_id)
    
    # 检查是否已有谜题
    if group_id in active_riddles:
        current = active_riddles[group_id]
        await start_riddle.finish(
            f"（敲桌子）还有谜题没猜出来呢！\n"
            f"{'='*20}\n"
            f"【{current['type']}】\n"
            f"{current['riddle']}\n"
            f"{'='*20}\n"
            f"/提示 - 查看提示\n"
            f"/放弃 - 公布答案"
        )
    
    # 生成谜语（最多重试3次避免重复）
    await start_riddle.send("（抚须）且慢，本猫正在想一个好题目...")
    
    riddle_data = None
    for _ in range(3):
        riddle_data = await generate_riddle(group_id)
        if riddle_data:
            break
    
    if not riddle_data:
        await start_riddle.finish(random.choice(ERROR_MESSAGES))
    
    start_msg = random.choice(START_MESSAGES)
    
    # 存储谜题
    active_riddles[group_id] = riddle_data
    
    await start_riddle.finish(
        f"🎭 李太白给·猜谜 🎭\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"【{riddle_data['type']}】\n"
        f"{riddle_data['riddle']}\n"
        f"{'='*20}\n"
        f"直接发送答案即可！\n"
        f"答对奖励 20 积分~\n"
        f"{'='*20}\n"
        f"/提示 - 查看提示\n"
        f"/放弃 - 公布答案\n"
        f"{'='*20}\n"
        f"『谜面一出考众生，\n猜中有奖猜错疼。\n诸位才子莫要慌，\n动动脑筋显神通~』"
    )

# 提示
hint_riddle = on_command("提示", priority=5, block=True)

@hint_riddle.handle()
async def handle_hint(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await hint_riddle.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_riddles:
        await hint_riddle.finish("（摊手）当前没有谜题！输入 /猜谜 开始~")
    
    current = active_riddles[group_id]
    hint_msg = random.choice(HINT_MESSAGES)
    
    # 额外提示：答案长度
    answer_len = len(current["answer"])
    len_hint = f"答案是{answer_len}个字"
    
    await hint_riddle.finish(
        f"🎭 猜谜提示 🎭\n"
        f"{'='*20}\n"
        f"{hint_msg}\n"
        f"{'='*20}\n"
        f"💡 {current['hint']}\n"
        f"💡 {len_hint}\n"
        f"{'='*20}\n"
        f"谜面：{current['riddle']}"
    )

# 放弃
give_up = on_command("放弃", aliases={"不猜了", "结束猜谜", "公布答案"}, priority=5, block=True)

@give_up.handle()
async def handle_give_up(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await give_up.finish("（摇头）要在群里玩哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_riddles:
        await give_up.finish("（摊手）当前没有谜题！")
    
    current = active_riddles[group_id]
    answer = current["answer"]
    giveup_msg = random.choice(GIVEUP_MESSAGES)
    
    # 记录已用谜底
    if group_id not in used_riddles:
        used_riddles[group_id] = []
    used_riddles[group_id].append(answer)
    if len(used_riddles[group_id]) > MAX_HISTORY:
        used_riddles[group_id] = used_riddles[group_id][-MAX_HISTORY:]
    
    del active_riddles[group_id]
    
    await give_up.finish(
        f"🎭 谜底揭晓 🎭\n"
        f"{'='*20}\n"
        f"{giveup_msg}\n"
        f"{'='*20}\n"
        f"谜面：{current['riddle']}\n"
        f"答案：【{answer}】\n"
        f"{'='*20}\n"
        f"『谜底揭开真相明，\n恍然大悟拍脑门。\n下次再来莫泄气，\n输入猜谜再出题~』"
    )

# 监听答案
def riddle_answer_rule(event: MessageEvent) -> bool:
    """检查是否是猜谜答案"""
    if not is_feature_enabled("riddle"):
        return False

    if not isinstance(event, GroupMessageEvent):
        return False
    group_id = str(event.group_id)
    if group_id not in active_riddles:
        return False
    msg = event.get_plaintext().strip()
    # 排除命令
    if msg.startswith("/"):
        return False
    # 太长的不处理（答案一般不会超过10个字）
    if len(msg) > 10:
        return False
    # 太短也不处理
    if len(msg) < 1:
        return False
    return True

answer_matcher = on_message(rule=Rule(riddle_answer_rule), priority=6, block=False)

@answer_matcher.handle()
async def handle_answer(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in active_riddles:
        return
    
    msg = event.get_plaintext().strip()
    current = active_riddles[group_id]
    
    # 严格验证答案
    if check_answer(msg, current["answer"]):
        # 答对了
        answer = current["answer"]
        
        # 记录已用谜底
        if group_id not in used_riddles:
            used_riddles[group_id] = []
        used_riddles[group_id].append(answer)
        if len(used_riddles[group_id]) > MAX_HISTORY:
            used_riddles[group_id] = used_riddles[group_id][-MAX_HISTORY:]
        
        del active_riddles[group_id]
        
        nickname = await get_nickname(bot, user_id, context="猜谜答对")
        
        # 奖励积分
        add_points(user_id, group_id, 20)
        
        correct_msg = random.choice(CORRECT_MESSAGES)
        
        await answer_matcher.finish(
            f"🎉 恭喜 {nickname} 答对了！🎉\n"
            f"{'='*20}\n"
            f"谜面：{current['riddle']}\n"
            f"答案：【{answer}】\n"
            f"{'='*20}\n"
            f"{correct_msg}\n"
            f"奖励 20 积分~\n"
            f"{'='*20}\n"
            f"『谜底被君一语破，\n才思敏捷真不错。\n本猫心服口服也，\n改日再来战一波~』\n"
            f"{'='*20}\n"
            f"输入 /猜谜 再来一题！"
        )

# 查看当前谜题
check_riddle = on_command("当前谜题", aliases={"看题", "谜题"}, priority=5, block=True)

@check_riddle.handle()
async def handle_check(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await check_riddle.finish("（摇头）要在群里查看哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_riddles:
        await check_riddle.finish("（摊手）当前没有谜题！输入 /猜谜 开始~")
    
    current = active_riddles[group_id]
    
    await check_riddle.finish(
        f"🎭 当前谜题 🎭\n"
        f"{'='*20}\n"
        f"【{current['type']}】\n"
        f"{current['riddle']}\n"
        f"{'='*20}\n"
        f"直接发送答案即可！\n"
        f"/提示 - 查看提示\n"
        f"/放弃 - 公布答案"
    )

