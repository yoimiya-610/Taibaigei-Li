import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
from common.ai_client import prompt_completion
from common.help_registry import HelpItem
from common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("诗词文艺", "/藏头诗 内容 - 创作藏头诗", 60),
    HelpItem("情感互动", "/情话 - 随机情话", 10),
    HelpItem("情感互动", "/表白 名字 - 代写表白", 20),
    HelpItem("情感互动", "/舔狗日记 - 随机舔狗日记", 30),
    HelpItem("情感互动", "/渣男语录 - 随机渣男语录", 40),
)
COMMAND_ALIASES = (
    "情话", "说情话", "土味情话", "撩我",
    "表白", "我喜欢", "告白",
    "藏头诗", "藏头诗表白", "写藏头诗",
    "舔狗日记", "舔狗", "卑微",
    "渣男语录", "渣男", "海王",
)

# 李太白给人设
SYSTEM_PROMPT = """你是"李太白给"，一只名为耄耋的猫猫头，喜欢穿着唐装，戴着墨镜，手持酒壶，满嘴诗词歌赋，但实际上是个花花公子。自称"本猫"。

文风要求：
1. 每句回复都带有"史诗感"或"文艺腔"
2. 用高雅词汇描述事物
3. 是个花花公子，喜欢释放廉价但有趣的爱意
4. 回复结尾可以附带一首原创小诗（打油诗/俳句/宋词风）
5. 每次回复都要有新意，不要重复之前的内容"""

# API出错文案
ERROR_MESSAGES = [
    "（扶额）本猫的脑子好像宕机了...容本猫缓缓，稍后再来~",
    "（揉太阳穴）哎呀，本猫今日诗兴不佳，改日再来吧~",
    "（打哈欠）本猫困了，让本猫休息一下再说...",
    "（晃酒壶）本猫喝多了，脑子转不动了，稍等片刻~",
]

async def call_api(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    """调用API，出错返回None"""
    return await prompt_completion(
        prompt,
        system=system,
        max_tokens=500,
        temperature=0.95,
    )

# 情话
love_words = on_command("情话", aliases={"说情话", "土味情话", "撩我"}, priority=5, block=True)

@love_words.handle()
async def handle_love(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="情话")
    
    factors = get_random_factors()
    
    # 情话类型随机
    love_types = ["土味情话", "古风情话", "文艺情话", "搞笑情话", "撩人情话", "甜蜜情话"]
    love_type = random.choice(love_types)
    
    base_prompt = f"""请对"{nickname}"说一句{love_type}。

要求：
1. 要有文艺气息，但又带点土味的反差萌
2. 可以用古诗词的意境来表达现代的撩人
3. 花花公子风格，有点油腻但又有点可爱
4. 结尾附带一首表白的打油诗或俳句
5. 不要重复之前说过的情话，要有新意"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("love_words", reply)
        await love_words.finish(
            f"💕 李太白给·情话时间 💕\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await love_words.finish(random.choice(ERROR_MESSAGES))

# 表白
confess = on_command("表白", aliases={"我喜欢", "告白"}, priority=5, block=True)

@confess.handle()
async def handle_confess(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    user_id = event.get_user_id()
    target = args.extract_plain_text().strip()
    
    nickname = await get_nickname(bot, user_id, context="表白")
    
    if not target:
        await confess.finish(
            f"（推墨镜）想表白？\n"
            f"{'='*20}\n"
            f"用法：/表白 对方名字\n"
            f"例如：/表白 小美\n"
            f"{'='*20}\n"
            f"本猫帮你写一封情书~"
        )
    
    factors = get_random_factors()
    
    base_prompt = f"""用户"{nickname}"想对"{target}"表白，请帮他/她写一段诗意的表白词。

要求：
1. 要用华丽、诗意的语言表达爱意
2. 要提到{nickname}对{target}的心意
3. 带有古典浪漫的意境
4. 结尾附带一首原创表白诗
5. 语气是李太白给代替{nickname}表白的感觉"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        await confess.finish(
            f"💌 李太白给·代为表白 💌\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await confess.finish(random.choice(ERROR_MESSAGES))

# 藏头诗
acrostic_love = on_command("藏头诗", aliases={"藏头诗表白", "写藏头诗"}, priority=5, block=True)

@acrostic_love.handle()
async def handle_acrostic(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    target = args.extract_plain_text().strip()
    
    if not target:
        await acrostic_love.finish(
            f"（抚须）想要藏头诗？\n"
            f"{'='*20}\n"
            f"用法：/藏头诗 想要藏的字\n"
            f"例如：/藏头诗 我爱你\n"
            f"例如：/藏头诗 小美我爱你\n"
            f"{'='*20}\n"
            f"本猫给你写一首暗藏玄机的诗~"
        )
    
    if len(target) > 10:
        await acrostic_love.finish("（摇头）太长了记不住...最多10个字~")
    
    prompt = f"""请写一首藏头诗，每句的第一个字连起来是"{target}"。

要求：
1. 必须是{len(target)}句，每句7个字
2. 每句第一个字连起来必须准确拼成"{target}"
3. 内容要有意境，可以与爱情、人生、自然相关
4. 要有古典诗词的意境和韵味
5. 尽量押韵

请直接输出诗句，每句换行，不要有其他解释。"""

    reply = await call_api(prompt, system="你是一位精通古典诗词的诗人。")
    
    if reply:
        await acrostic_love.finish(
            f"📜 李太白给·藏头诗 📜\n"
            f"{'='*20}\n"
            f"（挥毫泼墨）本猫献丑了~\n"
            f"{'='*20}\n"
            f"{reply}\n"
            f"{'='*20}\n"
            f"💡 藏头：{target}\n"
            f"{'='*20}\n"
            f"（推墨镜）发给想发的人吧~\n"
            f"看ta能不能发现其中玄机~"
        )
    else:
        await acrostic_love.finish(random.choice(ERROR_MESSAGES))

# 舔狗日记
lick_dog = on_command("舔狗日记", aliases={"舔狗", "卑微"}, priority=5, block=True)

@lick_dog.handle()
async def handle_lick(bot: Bot, event: MessageEvent):
    factors = get_random_factors()
    
    # 舔狗场景随机
    scenarios = [
        "她发了一条朋友圈", "她换了头像", "她在群里说话了",
        "她给我点了个赞", "她看了我的朋友圈", "她回复了我的消息",
        "她今天没理我", "她和别人聊天", "她说她很忙",
        "我给她买了奶茶", "我在她楼下等了三小时", "我又被她拉黑了"
    ]
    scenario = random.choice(scenarios)
    day_count = random.randint(100, 999)
    
    base_prompt = f"""请生成一条舔狗日记风格的内容。

场景：{scenario}
舔狗天数：第{day_count}天

要求：
1. 要有舔狗日记的卑微感，但用文艺的方式表达
2. 要有"虽然你不喜欢我但我还是爱你"的感觉
3. 带有李太白给的诗意和调侃
4. 结尾可以有一个反转或者自嘲
5. 最后附带一首卑微的打油诗
6. 要有新意，不要和之前的内容重复"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("lick_dog", reply)
        await lick_dog.finish(
            f"📔 李太白给·舔狗日记 📔\n"
            f"{'='*20}\n"
            f"第{day_count}天\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await lick_dog.finish(random.choice(ERROR_MESSAGES))

# 渣男语录
scum_words = on_command("渣男语录", aliases={"渣男", "海王"}, priority=5, block=True)

@scum_words.handle()
async def handle_scum(bot: Bot, event: MessageEvent):
    factors = get_random_factors()
    
    # 渣男类型随机
    scum_types = ["中央空调型", "时间管理大师型", "pua高手型", "备胎收集者型", "若即若离型", "嘴上说爱型"]
    scum_type = random.choice(scum_types)
    
    base_prompt = f"""请生成一条渣男语录/海王语录。

渣男类型：{scum_type}

要求：
1. 要有渣男的油腻感，但用文艺的方式包装
2. 要能让人一眼看出是渣男话术
3. 带有李太白给的诗意和调侃
4. 有一种"明知道他在渣但是好像有点道理"的感觉
5. 最后附带一首渣男打油诗
6. 要有新意，不要重复之前的内容"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("scum_words", reply)
        await scum_words.finish(
            f"🦈 李太白给·渣男语录 🦈\n"
            f"{'='*20}\n"
            f"【{scum_type}】\n"
            f"{'='*20}\n"
            f"{reply}\n"
            f"{'='*20}\n"
            f"⚠️ 以上为反面教材，请勿模仿！"
        )
    else:
        await scum_words.finish(random.choice(ERROR_MESSAGES))

