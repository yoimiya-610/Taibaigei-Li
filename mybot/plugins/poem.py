import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
from common.ai_client import prompt_completion
from common.help_registry import HelpItem


HELP_ITEMS = (
    HelpItem("诗词文艺", "/作诗 主题 - 即兴赋诗", 10),
    HelpItem("诗词文艺", "/解诗 诗句 - 诗词赏析", 20),
    HelpItem("诗词文艺", "/对对联 上联 - 对出下联", 30),
    HelpItem("诗词文艺", "/诗词接龙 字 - 开始诗词接龙", 40),
    HelpItem("诗词文艺", "/随机诗词 - 欣赏随机诗词", 50),
)
COMMAND_ALIASES = (
    "作诗", "写诗", "赋诗",
    "解诗", "诗词解析", "赏析",
    "对对联", "对联", "出上联", "对下联",
    "诗词接龙", "接诗", "接龙",
    "随机诗词", "来首诗", "随机古诗",
)

# 李太白给人设
SYSTEM_PROMPT = """你是"李太白给"，一只名为耄耋的猫猫头，喜欢穿着唐装，戴着墨镜，手持酒壶，满嘴诗词歌赋，但实际上是个花花公子。自称"本猫"。

你精通中国古典诗词，对唐诗宋词元曲了如指掌，能够作诗、解诗、对对联。
文风要求：
1. 回复带有"史诗感"或"文艺腔"
2. 用高雅词汇，展示深厚的文学功底
3. 带有花花公子式的调侃和风趣
4. 必要时附带原创诗歌点评"""

# API出错文案
ERROR_MESSAGES = [
    "（扶额）本猫的诗兴好像宕机了...容本猫缓缓~",
    "（揉太阳穴）哎呀，今日诗兴不佳，改日再来吧~",
    "（晃酒壶）本猫喝多了，脑子转不动了，稍等片刻~",
    "（叹气）本猫的灵感好像被酒精泡坏了，等会儿再试试？",
]

async def call_api(prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.9) -> str:
    """调用API，出错返回None"""
    return await prompt_completion(
        prompt,
        system=system,
        max_tokens=800,
        temperature=temperature,
    )

# ==================== 作诗 ====================
write_poem = on_command("作诗", aliases={"写诗", "赋诗"}, priority=5, block=True)

@write_poem.handle()
async def handle_write_poem(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    theme = args.extract_plain_text().strip()
    
    if not theme:
        await write_poem.finish(
            f"（抚须）想让本猫作诗？\n"
            f"{'='*20}\n"
            f"用法：/作诗 主题\n"
            f"例如：/作诗 春天\n"
            f"例如：/作诗 思念故乡\n"
            f"{'='*20}\n"
            f"本猫诗兴大发，随时恭候~"
        )
    
    # 随机选择诗体
    poem_types = ["五言绝句", "七言绝句", "五言律诗", "七言律诗", "词（自选词牌）"]
    poem_type = random.choice(poem_types)
    
    prompt = f"""请以"{theme}"为主题，创作一首{poem_type}。

要求：
1. 符合{poem_type}的格律要求
2. 意境优美，有古典诗词的韵味
3. 内容与主题"{theme}"相关
4. 创作完成后，以李太白给的口吻简单点评这首诗
5. 点评要风趣幽默，带有花花公子的调侃"""

    reply = await call_api(prompt)
    
    if reply:
        await write_poem.finish(
            f"📜 李太白给·即兴赋诗 📜\n"
            f"{'='*20}\n"
            f"（提笔蘸墨）主题：{theme}\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await write_poem.finish(random.choice(ERROR_MESSAGES))

# ==================== 解诗 ====================
explain_poem = on_command("解诗", aliases={"诗词解析", "赏析"}, priority=5, block=True)

@explain_poem.handle()
async def handle_explain_poem(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    poem_text = args.extract_plain_text().strip()
    
    if not poem_text:
        await explain_poem.finish(
            f"（推墨镜）想让本猫解诗？\n"
            f"{'='*20}\n"
            f"用法：/解诗 诗句或诗名\n"
            f"例如：/解诗 床前明月光\n"
            f"例如：/解诗 静夜思\n"
            f"例如：/解诗 春眠不觉晓，处处闻啼鸟\n"
            f"{'='*20}\n"
            f"本猫学富五车，定能为你解惑~"
        )
    
    prompt = f"""请解析以下诗词："{poem_text}"

请按以下格式回答：
1. 【出处】这首诗/词的作者、朝代、作品名（如果是名句，补全整首诗）
2. 【译文】用现代文翻译这首诗的意思
3. 【意境】分析诗词的意境和情感
4. 【手法】分析使用的修辞手法和写作技巧
5. 【名句】如果有流传千古的名句，特别点评
6. 【本猫点评】以李太白给的口吻，用风趣幽默的方式点评这首诗，可以联系现代生活

如果不是真实存在的诗词，请指出并给出可能相似的真实诗词。"""

    reply = await call_api(prompt, temperature=0.7)
    
    if reply:
        await explain_poem.finish(
            f"📖 李太白给·诗词赏析 📖\n"
            f"{'='*20}\n"
            f"（扶正墨镜）让本猫来品一品~\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await explain_poem.finish(random.choice(ERROR_MESSAGES))

# ==================== 对对联 ====================
couplet = on_command("对对联", aliases={"对联", "出上联", "对下联"}, priority=5, block=True)

@couplet.handle()
async def handle_couplet(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    upper = args.extract_plain_text().strip()
    
    if not upper:
        await couplet.finish(
            f"（抚须）想和本猫对对联？\n"
            f"{'='*20}\n"
            f"用法：/对对联 上联\n"
            f"例如：/对对联 风吹柳絮满店香\n"
            f"例如：/对对联 海内存知己\n"
            f"{'='*20}\n"
            f"本猫来者不拒，尽管出题~"
        )
    
    prompt = f"""请对出下联。

上联：{upper}

要求：
1. 严格遵守对联规则：字数相等、词性相对、平仄相对
2. 内容要与上联意境呼应或形成对比
3. 尽量工整、有文采

请按以下格式回答：
上联：{upper}
下联：[你的下联]

【解析】
- 词性对应：分析上下联的词性对应关系
- 平仄分析：简单说明平仄是否相对
- 意境说明：解释下联的含义以及与上联的关系

【本猫点评】以李太白给的风格，风趣地点评这副对联"""

    reply = await call_api(prompt, temperature=0.8)
    
    if reply:
        await couplet.finish(
            f"🎋 李太白给·对对联 🎋\n"
            f"{'='*20}\n"
            f"（摇扇子）让本猫来会一会~\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await couplet.finish(random.choice(ERROR_MESSAGES))

# ==================== 诗词接龙 ====================
poetry_chain = on_command("诗词接龙", aliases={"接诗", "接龙"}, priority=5, block=True)

@poetry_chain.handle()
async def handle_poetry_chain(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    char = args.extract_plain_text().strip()
    
    if not char:
        await poetry_chain.finish(
            f"（晃酒壶）想玩诗词接龙？\n"
            f"{'='*20}\n"
            f"用法：/诗词接龙 字\n"
            f"例如：/诗词接龙 月\n"
            f"例如：/诗词接龙 春\n"
            f"{'='*20}\n"
            f"给本猫一个字，本猫给你一句诗~"
        )
    
    if len(char) > 2:
        await poetry_chain.finish("（摇头）给本猫一个字就行，不要贪多~")
    
    # 取第一个字
    char = char[0]
    
    prompt = f"""请给出一句以"{char}"字开头的古诗词名句。

要求：
1. 必须是真实存在的古诗词名句（唐诗、宋词、元曲、古文等皆可）
2. 诗句必须以"{char}"字开头
3. 尽量选择脍炙人口的名句

请按以下格式回答：
诗句：[以"{char}"开头的诗句]
出处：[作者]《[作品名]》
全诗/词：[如果是节选，给出完整的诗或那一段]

【下一个字】这句诗的最后一个字是"X"，下次可以用"/诗词接龙 X"继续~

【本猫点评】用风趣的方式简单点评这句诗"""

    reply = await call_api(prompt, temperature=0.8)
    
    if reply:
        await poetry_chain.finish(
            f"🔗 李太白给·诗词接龙 🔗\n"
            f"{'='*20}\n"
            f"（抚须）「{char}」字开头？简单~\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await poetry_chain.finish(random.choice(ERROR_MESSAGES))

# ==================== 随机诗词 ====================
random_poem = on_command("随机诗词", aliases={"来首诗", "随机古诗"}, priority=5, block=True)

@random_poem.handle()
async def handle_random_poem(bot: Bot, event: MessageEvent):
    from plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
    
    factors = get_random_factors()
    
    # 随机选择诗词类型和主题
    poem_types = ["唐诗", "宋词", "元曲", "古文名篇", "先秦诗歌", "魏晋诗歌", "明清诗词"]
    themes = ["山水田园", "边塞征战", "思乡怀人", "咏史怀古", "送别", 
              "爱情", "哲理", "咏物", "节日", "闺怨", "豪放", "婉约",
              "隐逸", "怀才不遇", "羁旅", "讽喻", "悼亡"]
    
    poem_type = random.choice(poem_types)
    theme = random.choice(themes)
    
    # 作者范围随机
    author_hints = [
        "李白、杜甫、白居易等唐代诗人",
        "苏轼、辛弃疾、李清照等宋代词人",
        "陶渊明、谢灵运等魏晋诗人",
        "王维、孟浩然等山水诗人",
        "高适、岑参等边塞诗人",
        "李商隐、杜牧等晚唐诗人",
        "不限作者，选一首冷门但优秀的",
    ]
    author_hint = random.choice(author_hints)
    
    base_prompt = f"""请推荐一首{poem_type}，主题与"{theme}"相关。

作者范围：{author_hint}

要求：
1. 必须是真实存在的著名诗词
2. 给出完整的诗词内容
3. 尽量推荐与之前不同的诗词

请按以下格式回答：
【作品】《[作品名]》
【作者】[朝代] [作者名]
【类型】{poem_type} · {theme}

[完整诗词内容]

【译文】用现代文翻译诗词大意

【赏析】简要分析诗词的意境、情感和艺术特色

【名句】如果有流传千古的名句，特别指出

【本猫点评】以李太白给的风格，风趣地点评这首诗词"""

    prompt = build_random_prompt(base_prompt, factors)
    reply = await call_api(prompt, temperature=0.95)
    
    if reply:
        add_to_cache("random_poem", reply)
        await random_poem.finish(
            f"📚 李太白给·每日一诗 📚\n"
            f"{'='*20}\n"
            f"（翻开诗集）今日本猫推荐这首~\n"
            f"{'='*20}\n"
            f"{reply}"
        )
    else:
        await random_poem.finish(random.choice(ERROR_MESSAGES))

