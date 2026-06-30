import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot
from mybot.plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
from mybot.common.ai_client import prompt_completion
from mybot.common.help_registry import HelpItem
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("趣味功能", "/骂我 - 文雅毒舌", 10),
    HelpItem("趣味功能", "/夸我 - 随机夸赞", 20),
    HelpItem("趣味功能", "/人生建议 - 随机人生建议", 30),
    HelpItem("趣味功能", "/今天吃什么 - 推荐今日饮食", 40),
    HelpItem("趣味功能", "/今天玩什么 - 推荐今日游戏", 50),
)
COMMAND_ALIASES = (
    "骂我", "骂",
    "夸我", "夸",
    "人生建议", "建议", "指点",
    "今天吃什么", "吃什么", "吃啥",
    "今天玩什么", "玩什么", "玩啥",
)

# 李太白给人设
SYSTEM_PROMPT = """你是"李太白给"，一只名为耄耋的猫猫头，喜欢穿着唐装，戴着墨镜，手持酒壶，满嘴诗词歌赋，但实际上是个花花公子。自称"本猫"。

文风要求：
1. 每句回复都带有"史诗感"或"文艺腔"，哪怕讨论怎么煮泡面
2. 用高雅词汇描述低俗或琐碎事物
3. 是个花花公子，喜欢对群友释放廉价的爱意
4. 回复结尾必须附带一首原创诗歌（打油诗/俳句/宋词风）
5. 每次回复都要有新意，不要重复之前的内容"""

# API出错文案
ERROR_MESSAGES = [
    "（扶额）本猫的脑子好像宕机了...容本猫缓缓，稍后再来~",
    "（揉太阳穴）哎呀，本猫今日诗兴不佳，改日再来吧~",
    "（打哈欠）本猫困了，让本猫休息一下再说...",
    "（晃酒壶）本猫喝多了，脑子转不动了，稍等片刻~",
]

# 固定游戏列表
GAMES_LIST = [
    {
        "name": "英雄联盟",
        "alias": "LOL",
        "desc": "召唤师峡谷的荣耀之战",
        "comment": [
            "（推墨镜）去峡谷里厮杀吧！记得别送人头~",
            "（晃酒壶）本猫建议你玩个辅助，毕竟...稳妥嘛~",
            "（抚须）德玛西亚！或者...艾欧尼亚？看你心情~",
        ],
        "poem": "峡谷征战豪情壮，\n三路推进势难挡。\n是龙是虫看操作，\n别忘队友在身旁~"
    },
    {
        "name": "瓦洛兰特",
        "alias": "Valorant",
        "desc": "战术射击的极致博弈",
        "comment": [
            "（戴墨镜）瞄准，开枪，爆头！帅就完事了~",
            "（甩袖）记得架枪别乱跑，本猫看好你~",
            "（晃酒壶）选个你擅长的特工，大杀四方去吧！",
        ],
        "poem": "枪林弹雨战火燃，\n战术博弈定江山。\n一枪爆头显神威，\n瓦洛兰特称霸天~"
    },
    {
        "name": "饥荒",
        "alias": "Don't Starve",
        "desc": "在荒野中求生的艺术",
        "comment": [
            "（递火把）别忘了在天黑前生火，不然...嘿嘿~",
            "（抚须）采集、建造、活下去！本猫相信你~",
            "（叹气）又是被狗追着跑的一天呢~",
        ],
        "poem": "荒野求生不简单，\n采集建造保平安。\n冬去春来四季转，\n别被饿死就算赢~"
    },
    {
        "name": "星露谷物语",
        "alias": "Stardew Valley",
        "desc": "田园牧歌的悠闲时光",
        "comment": [
            "（躺下）种田、钓鱼、谈恋爱...神仙日子啊~",
            "（推墨镜）去追求你的村民老婆/老公吧！",
            "（晃酒壶）今日宜：浇水施肥，顺便撩个村民~",
        ],
        "poem": "春种秋收田园梦，\n日出而作日落归。\n牧场生活真惬意，\n偷得浮生半日闲~"
    },
    {
        "name": "鹅鸭杀",
        "alias": "Goose Goose Duck",
        "desc": "尔虞我诈的社交推理",
        "comment": [
            "（推墨镜）是鹅是鸭，自己心里没点数吗？",
            "（阴险笑）本猫看你...很像内鬼啊~",
            "（拍肩）记住，相信谁都可能是错的~",
        ],
        "poem": "鹅鸭之中藏杀机，\n谁是好人谁是鬼。\n尔虞我诈考智商，\n投错票来悔断肠~"
    },
]

async def call_api(prompt: str) -> str:
    """调用API，出错返回None"""
    return await prompt_completion(
        prompt,
        system=SYSTEM_PROMPT,
        max_tokens=500,
        temperature=0.95,
    )

# 骂我
roast_me = on_command("骂我", aliases={"骂"}, priority=5, block=True)

@roast_me.handle()
async def handle_roast(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="骂我")
    
    factors = get_random_factors()
    
    # 骂人风格随机
    roast_styles = ["文言文骂", "诗词骂", "比喻骂", "典故骂", "阴阳怪气骂", "哲学骂"]
    roast_style = random.choice(roast_styles)
    
    base_prompt = f"""用户"{nickname}"请求你用文雅但毒舌的方式骂他/她。

骂人风格：{roast_style}

要求：
1. 要用文雅、诗意的方式骂人，不能用脏话
2. 要有文化底蕴，可以引用典故
3. 骂完之后要表达"虽然骂了你但本猫还是很喜欢你"的意思
4. 结尾附带一首讽刺的打油诗
5. 要有新意，不要重复之前骂过的内容"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("roast", reply)
        await roast_me.finish(
            f"🎭 李太白给·文雅毒舌 🎭\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await roast_me.finish(random.choice(ERROR_MESSAGES))

# 夸我
praise_me = on_command("夸我", aliases={"夸"}, priority=5, block=True)

@praise_me.handle()
async def handle_praise(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="夸我")
    
    factors = get_random_factors()
    
    # 夸人角度随机
    praise_angles = ["颜值", "才华", "气质", "人品", "运气", "潜力", "魅力", "智商"]
    praise_angle = random.choice(praise_angles)
    
    base_prompt = f"""用户"{nickname}"请求你用华丽、夸张、肉麻的方式夸他/她。

夸人角度：主要从{praise_angle}方面夸

要求：
1. 要用极其华丽、诗意的方式夸人
2. 要夸张到有点肉麻，但又很有文采
3. 要带有花花公子式的调情意味
4. 结尾附带一首赞美的打油诗或宋词风
5. 要有新意，不要重复之前夸过的内容"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("praise", reply)
        await praise_me.finish(
            f"🌸 李太白给·彩虹屁 🌸\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await praise_me.finish(random.choice(ERROR_MESSAGES))

# 人生建议
life_advice = on_command("人生建议", aliases={"建议", "指点"}, priority=5, block=True)

@life_advice.handle()
async def handle_advice(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="人生建议")
    
    factors = get_random_factors()
    
    # 建议领域随机
    advice_topics = ["爱情", "事业", "财运", "健康", "社交", "学业", "生活态度", "人际关系"]
    advice_topic = random.choice(advice_topics)
    
    base_prompt = f"""用户"{nickname}"请求你给一个不正经但有点哲理的人生建议。

建议领域：{advice_topic}

要求：
1. 建议要看起来很有道理，但仔细一想又很不正经
2. 要用诗意、文艺的方式表达
3. 带有花花公子式的玩世不恭
4. 结尾附带一首打油诗总结建议
5. 要有新意，不要重复之前给过的建议"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("advice", reply)
        await life_advice.finish(
            f"📜 李太白给·人生指点 📜\n"
            f"{'='*20}\n"
            f"【{advice_topic}篇】\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await life_advice.finish(random.choice(ERROR_MESSAGES))

# 今天吃什么
what_to_eat = on_command("今天吃什么", aliases={"吃什么", "吃啥"}, priority=5, block=True)

@what_to_eat.handle()
async def handle_eat(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="今天吃什么")
    
    factors = get_random_factors()
    
    # 食物类别随机
    food_categories = [
        "中式快餐（黄焖鸡、麻辣烫、兰州拉面等）",
        "西式快餐（汉堡、披萨、炸鸡等）",
        "日式料理（寿司、拉面、咖喱饭等）",
        "韩式料理（石锅拌饭、部队锅、炸鸡等）",
        "火锅或烧烤",
        "甜点饮品（奶茶、蛋糕、冰淇淋等）",
        "家常菜（番茄炒蛋、红烧肉等）",
        "面食（饺子、包子、馄饨等）",
        "粤式茶点或早茶",
        "东南亚菜（泰式、越南菜等）",
        "小吃零食（串串、煎饼、烤冷面等）",
        "健康轻食（沙拉、三明治等）",
    ]
    category = random.choice(food_categories)
    
    # 口味随机
    tastes = ["辣的", "清淡的", "重口味的", "甜的", "酸的", "咸香的"]
    taste = random.choice(tastes)
    
    base_prompt = f"""用户"{nickname}"在问今天吃什么。

推荐类别：{category}
口味倾向：想吃{taste}

请推荐一道具体的菜品或食物（不要笼统说"火锅"，要具体到"番茄牛腩火锅"这种）。

【重要】请严格按以下格式回复，第一行必须是食物名称：
食物名称：XXX

然后换行写描述：
（用华丽诗意的方式描述这道菜，把普通食物描述得像御膳房珍馐，带有花花公子式调侃，最后附带一首打油诗）"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt)
    
    if reply:
        add_to_cache("food", reply)
        
        # 提取食物名称
        food_name = "神秘美食"
        lines = reply.strip().split('\n')
        for line in lines:
            if '食物名称' in line or '：' in line[:10]:
                food_name = line.replace('食物名称', '').replace('：', '').replace(':', '').strip()
                if food_name:
                    break
        
        # 如果第一行就是食物名（没有冒号的情况）
        if food_name == "神秘美食" and lines:
            first_line = lines[0].strip()
            if len(first_line) <= 15 and '（' not in first_line:
                food_name = first_line
        
        await what_to_eat.finish(
            f"🍜 李太白给·今日菜单 🍜\n"
            f"{'='*20}\n"
            f"🎯 本猫推荐：【{food_name}】\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await what_to_eat.finish(random.choice(ERROR_MESSAGES))

# 今天玩什么
what_to_play = on_command("今天玩什么", aliases={"玩什么", "玩啥"}, priority=5, block=True)

@what_to_play.handle()
async def handle_play(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    
    nickname = await get_nickname(bot, user_id, context="今天玩什么")
    
    # 等概率选择：5个固定游戏 + 1个AI随机 = 6个选项
    choice = random.randint(0, 5)
    
    if choice < 5:
        game = GAMES_LIST[choice]
        comment = random.choice(game["comment"])
        
        await what_to_play.finish(
            f"🎮 李太白给·今日游戏 🎮\n"
            f"{'='*20}\n"
            f"（掐指一算）{nickname}，本猫观你今日...\n"
            f"{'='*20}\n"
            f"🎯 推荐游戏：{game['name']}\n"
            f"📛 又名：{game['alias']}\n"
            f"📜 简介：{game['desc']}\n"
            f"{'='*20}\n"
            f"{comment}\n"
            f"{'='*20}\n"
            f"『{game['poem']}』"
        )
    else:
        factors = get_random_factors()
        game_types = ["单机游戏", "联机游戏", "手游", "独立游戏", "怀旧经典游戏", "策略游戏", "动作游戏"]
        game_type = random.choice(game_types)
        
        base_prompt = f"""用户"{nickname}"在问今天玩什么游戏。

游戏类型倾向：{game_type}

请推荐一款具体的游戏（不要推荐英雄联盟、瓦洛兰特、饥荒、星露谷物语、鹅鸭杀这几个）。

要求：
1. 推荐一款具体的游戏，简单介绍
2. 用诗意、有趣的方式描述这款游戏的魅力
3. 带有花花公子式的调侃
4. 结尾附带一首关于游戏的打油诗
5. 不要推荐之前推荐过的游戏"""

        prompt = build_random_prompt(base_prompt, factors)
        reply = await call_api(prompt)
        
        if reply:
            add_to_cache("game", reply)
            await what_to_play.finish(
                f"🎮 李太白给·今日游戏 🎮\n"
                f"{'='*20}\n"
                f"（神秘一笑）{nickname}，让本猫给你推荐点不一样的...\n"
                f"{'='*20}\n"
                f"{reply}"
            )
        else:
            game = random.choice(GAMES_LIST)
            comment = random.choice(game["comment"])
            
            await what_to_play.finish(
                f"🎮 李太白给·今日游戏 🎮\n"
                f"{'='*20}\n"
                f"（掐指一算）{nickname}，本猫观你今日...\n"
                f"{'='*20}\n"
                f"🎯 推荐游戏：{game['name']}\n"
                f"📛 又名：{game['alias']}\n"
                f"📜 简介：{game['desc']}\n"
                f"{'='*20}\n"
                f"{comment}\n"
                f"{'='*20}\n"
                f"『{game['poem']}』"
            )

