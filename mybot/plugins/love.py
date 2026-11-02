from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="love",
    name="情感互动",
    default_enabled=True,
    scope="group",
    permission_level=2,
    privacy_level="personal",
    backup_policy="none",
)

import hashlib
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from mybot.plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
from mybot.common.ai_client import prompt_completion
from mybot.common.help_registry import HelpItem
from mybot.common.message_utils import get_first_at_user_id
from mybot.common.persona import GENERATION_FAILURE_MESSAGES, build_persona_prompt
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("诗词文艺", "/藏头诗 内容 - 创作藏头诗", 60),
    HelpItem("情感互动", "/情话 - 随机情话", 10),
    HelpItem("情感互动", "/表白 名字 - 代写表白", 20),
    HelpItem("情感互动", "/舔狗日记 - 随机舔狗日记", 30),
    HelpItem("情感互动", "/渣男语录 - 随机渣男语录", 40),
    HelpItem("情感互动", "/缘分签 @某人 - 抽今日缘分", 50),
    HelpItem("情感互动", "/夸夸 @某人 - 夸赞群友", 60),
    HelpItem("情感互动", "/借酒说话 内容 - 把话说软", 70),
    HelpItem("情感互动", "/今日心动 - 抽今日心动小事", 80),
)
COMMAND_ALIASES = (
    "情话", "说情话", "土味情话", "撩我",
    "表白", "我喜欢", "告白",
    "藏头诗", "藏头诗表白", "写藏头诗",
    "舔狗日记", "舔狗", "卑微",
    "渣男语录", "渣男", "海王",
    "缘分签", "缘分", "今日缘分",
    "夸夸", "夸夸他", "夸夸她", "夸夸TA",
    "借酒说话", "酒后真言", "替我说",
    "今日心动", "心动", "今天心动",
)

SYSTEM_PROMPT = build_persona_prompt(
    """你负责情话、表白、夸赞和替群友把话说软。表达浪漫、亲近、有新意，可以略带风流调侃，但不得油腻、贬低、操控或越过对方边界。
涉及真实关系时不替用户编造承诺，不把玩笑包装成事实；先照顾人的感受，再追求文艺效果。"""
)

ACROSTIC_SYSTEM_PROMPT = build_persona_prompt(
    """你精通古典诗词，现在只创作符合指定藏头与行数的诗句。只输出诗句，每句换行，不解释。""",
    require_ending_poem=False,
    use_persona_voice=False,
)

ERROR_MESSAGES = GENERATION_FAILURE_MESSAGES


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_TIPSY_TEXT_LENGTH = 120

FATE_SIGNS = (
    {
        "name": "饭搭子签",
        "tone": "一筷一盏最相宜，今日同桌不冷场。",
        "good": "宜约饭、宜分享菜单、宜把最后一块肉让出去半秒。",
        "avoid": "忌抢对方奶茶里的珍珠。",
        "poem": "一桌烟火映眉弯，\n半碗清汤也作欢。\n若问缘从何处起，\n大约同馋在人间。",
    },
    {
        "name": "诗友签",
        "tone": "两人今日适合互递灵感，胡话也能磨出三分光。",
        "good": "宜互相接梗、宜分享歌单、宜把废话说得像风雅。",
        "avoid": "忌把对方的好句当场拆台。",
        "poem": "一笺小字落群窗，\n半句闲谈也带香。\n今夜若逢诗兴起，\n借君笑意写三行。",
    },
    {
        "name": "互坑搭子签",
        "tone": "缘分像一只歪酒杯，越互相使坏越有热闹。",
        "good": "宜开玩笑、宜组队摸鱼、宜把锅轻轻推过去又接回来。",
        "avoid": "忌下手太狠，玩笑要留退路。",
        "poem": "你挖小坑我递锹，\n笑声一落满江潮。\n莫嫌今日风波浅，\n损友原来最耐聊。",
    },
    {
        "name": "贵人签",
        "tone": "今日一个顺手帮忙，一个正好接住，像风替灯添了半寸亮。",
        "good": "宜求助、宜提醒、宜把谢谢说得认真一点。",
        "avoid": "忌把好意当理所当然。",
        "poem": "灯前有人替君忙，\n一寸微光胜月霜。\n他日还将春色借，\n莫教人意落空囊。",
    },
    {
        "name": "同频签",
        "tone": "今日容易笑到同一个点上，连沉默都像在暗中点头。",
        "good": "宜一起吐槽、宜同步摸鱼、宜发只有彼此懂的表情。",
        "avoid": "忌突然认真到把气氛拧紧。",
        "poem": "一声轻笑隔屏来，\n两盏闲心并蒂开。\n莫问知音何处认，\n同频便是小蓬莱。",
    },
    {
        "name": "江湖同行签",
        "tone": "今日适合一起办事，一人执伞一人看路，颇有点并肩的意思。",
        "good": "宜组队、宜赶工、宜互相打气。",
        "avoid": "忌半路装作不认识。",
        "poem": "并肩踏过小风尘，\n酒壶轻响作军文。\n路远不妨同走去，\n回头皆是有缘人。",
    },
)

PRAISE_LINES = (
    "本猫看 {target} 今日眉眼带光，像把春风藏进袖口，随手一抬都能让群里亮三分。",
    "{target} 这份气质，属于茶要烫着敬、话要挑好听的说，寻常夸法配不上。",
    "若群聊也有风景榜，{target} 今日少说能坐前三，另外两名还得看本猫心情。",
    "{target} 的厉害不响，却像好酒，初闻清淡，细品才知后劲能把月亮都劝下来。",
    "本猫替 {sender} 认真夸一句：{target} 是那种一出现，连冷场都愿意自己退下的人。",
    "今日 {target} 的运势大约写着两个字：好看。四个字：很会发光。",
)

PRAISE_POEMS = (
    "云边借得三分色，\n落在君前作锦章。\n若问群中谁可赞，\n此人一笑胜春光。",
    "清风识得好人家，\n绕袖偏来赠晚霞。\n本猫夸人从不浅，\n今日此赞正开花。",
    "不必高声动四方，\n自有明珠在暗藏。\n一朝照入群窗里，\n满座都知是好光。",
)

HEARTBEAT_ITEMS = (
    {
        "name": "热奶茶第一口",
        "detail": "甜意刚好落在舌尖，像今日被世界轻轻放过一次。",
        "advice": "给自己买点小甜头，别把一天过得太硬。",
    },
    {
        "name": "傍晚一阵风",
        "detail": "风不大，却正好替心口松了个结。",
        "advice": "适合散步三分钟，顺便把烦事吹散半分。",
    },
    {
        "name": "消息框里的秒回",
        "detail": "有人正好在，有人正好回，热闹便有了落脚处。",
        "advice": "想念谁就说一句，别把好意闷成隔夜茶。",
    },
    {
        "name": "摸鱼成功的一瞬",
        "detail": "忙里偷闲不算懒，是凡人给灵魂续杯。",
        "advice": "今日可偷一点小闲，但别把正事全丢进酒壶。",
    },
    {
        "name": "路边灯亮起来",
        "detail": "天色一暗，灯火替人间把温柔接上。",
        "advice": "适合早点回家，也适合给自己留盏灯。",
    },
    {
        "name": "一句突然的夸奖",
        "detail": "好话落在耳边，像小小烟花，炸得心里亮了一下。",
        "advice": "今日也夸夸别人，光会越传越亮。",
    },
)


def current_date_text() -> str:
    return datetime.now(APP_TIMEZONE).strftime("%Y-%m-%d")


def _stable_number(parts: tuple[str, ...], modulo: int) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def _pair_key(user_id: str, target_id: str) -> str:
    return "|".join(sorted((str(user_id), str(target_id))))


def _pick_fate(date_text: str, group_id: str, user_id: str, target_id: str) -> tuple[dict[str, str], int]:
    pair = _pair_key(user_id, target_id)
    sign = FATE_SIGNS[_stable_number((date_text, group_id, pair, "sign"), len(FATE_SIGNS))]
    score = 60 + _stable_number((date_text, group_id, pair, "score"), 41)
    return sign, score


def _render_fate_message(
    sender_name: str,
    target_name: str,
    date_text: str,
    group_id: str,
    user_id: str,
    target_id: str,
) -> str:
    sign, score = _pick_fate(date_text, group_id, user_id, target_id)
    return (
        "💞 李太白给·缘分签 💞\n"
        f"{'='*22}\n"
        f"（拈起红笺）今日 {sender_name} 与 {target_name} 的签面：\n"
        f"【{sign['name']}】缘分值：{score}\n"
        f"{'='*22}\n"
        f"签语：{sign['tone']}\n"
        f"{sign['good']}\n"
        f"{sign['avoid']}\n"
        f"{'='*22}\n"
        f"『{sign['poem']}』"
    )


def _render_praise_message(sender_name: str, target_name: str, rng=random) -> str:
    line = rng.choice(PRAISE_LINES).format(sender=sender_name, target=target_name)
    poem = rng.choice(PRAISE_POEMS)
    return (
        "🌸 李太白给·夸夸笺 🌸\n"
        f"{'='*22}\n"
        f"（端起酒壶）{sender_name} 递来一朵彩云，点名要夸 {target_name}。\n"
        f"{'='*22}\n"
        f"{line}\n"
        f"{'='*22}\n"
        f"『{poem}』"
    )


def _pick_heartbeat(date_text: str, user_id: str) -> tuple[dict[str, str], int]:
    item = HEARTBEAT_ITEMS[_stable_number((date_text, user_id, "heartbeat"), len(HEARTBEAT_ITEMS))]
    score = 70 + _stable_number((date_text, user_id, "heartbeat-score"), 31)
    return item, score


def _render_today_heartbeat(nickname: str, date_text: str, user_id: str) -> str:
    item, score = _pick_heartbeat(date_text, user_id)
    return (
        "💗 李太白给·今日心动 💗\n"
        f"{'='*22}\n"
        f"（抬眼看云）{nickname} 今日的心动小事：\n"
        f"【{item['name']}】心动值：{score}\n"
        f"{'='*22}\n"
        f"{item['detail']}\n"
        f"{item['advice']}\n"
        f"{'='*22}\n"
        "『心上一灯轻轻亮，\n"
        "人间小事也成章。\n"
        "莫嫌今日风光浅，\n"
        "一点欢喜抵千霜。』"
    )


def _build_tipsy_prompt(nickname: str, raw_text: str) -> str:
    return f"""用户"{nickname}"想借李太白给的酒劲，把下面这句话说得更委婉、更有人情味。

原话：
{raw_text}

要求：
1. 不改变原意，不额外编造承诺或事实
2. 适合直接发给别人，语气真诚、轻松、不要攻击人
3. 带一点李太白给式动作旁白、酒意和诗意，但不要油腻过头
4. 输出一段改写后的话，结尾附带四句短诗
5. 不要解释你做了什么，直接给可发送文本"""


async def call_api(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    """调用API，出错返回None"""
    return await prompt_completion(
        prompt,
        system=system,
        max_tokens=500,
        temperature=0.95,
    )


# 缘分签
fate_sign = on_command("缘分签", aliases={"缘分", "今日缘分"}, priority=5, block=True)

@fate_sign.handle()
async def handle_fate_sign(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await fate_sign.finish(
            "（收起红笺）缘分签要在群里当面抽，旁人一笑才有热闹。\n"
            "『红线须从人海过，一签方见两心灯。』"
        )

    target_id = get_first_at_user_id(args)
    if not target_id:
        await fate_sign.finish(
            "💞 李太白给·缘分签 💞\n"
            f"{'='*22}\n"
            "用法：/缘分签 @某人\n"
            "本猫只认真正的 @，不靠昵称猜人。\n"
            f"{'='*22}\n"
            "『红笺须点有缘客，莫把同名乱作签。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    sender_name = await get_nickname(bot, user_id, context="缘分签.sender")
    target_name = await get_nickname(bot, target_id, context="缘分签.target")

    await fate_sign.finish(
        _render_fate_message(
            sender_name,
            target_name,
            current_date_text(),
            group_id,
            user_id,
            target_id,
        )
    )


# 夸夸
praise_someone = on_command("夸夸", aliases={"夸夸他", "夸夸她", "夸夸TA"}, priority=5, block=True)

@praise_someone.handle()
async def handle_praise_someone(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await praise_someone.finish(
            "（铺开花笺）夸夸要在群里喊出来，才算满座生花。\n"
            "『好话若从群里落，一枝春色照千屏。』"
        )

    target_id = get_first_at_user_id(args)
    if not target_id:
        await praise_someone.finish(
            "🌸 李太白给·夸夸笺 🌸\n"
            f"{'='*22}\n"
            "用法：/夸夸 @某人\n"
            "本猫只认真正的 @，夸错人可就尴尬了。\n"
            f"{'='*22}\n"
            "『夸人须向真名去，春风不可乱吹花。』"
        )

    user_id = event.get_user_id()
    sender_name = await get_nickname(bot, user_id, context="夸夸.sender")
    target_name = await get_nickname(bot, target_id, context="夸夸.target")

    await praise_someone.finish(_render_praise_message(sender_name, target_name))


# 借酒说话
tipsy_words = on_command("借酒说话", aliases={"酒后真言", "替我说"}, priority=5, block=True)

@tipsy_words.handle()
async def handle_tipsy_words(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    raw_text = args.extract_plain_text().strip()
    if not raw_text:
        await tipsy_words.finish(
            "🍶 李太白给·借酒说话 🍶\n"
            f"{'='*22}\n"
            "用法：/借酒说话 想说但不好开口的话\n"
            "例如：/借酒说话 最近辛苦了，想请你喝杯奶茶\n"
            f"{'='*22}\n"
            "『话到唇边嫌太直，本猫替你酿三分。』"
        )

    if len(raw_text) > MAX_TIPSY_TEXT_LENGTH:
        await tipsy_words.finish(
            f"（按住酒杯）这段话太长了，本猫一口酒装不下。\n"
            f"请压到 {MAX_TIPSY_TEXT_LENGTH} 字以内，再让本猫替你润色。\n"
            "『长话且裁三两句，酒香才好入人心。』"
        )

    nickname = await get_nickname(bot, event.get_user_id(), context="借酒说话")
    prompt = build_random_prompt(_build_tipsy_prompt(nickname, raw_text), get_random_factors())
    reply = await call_api(prompt)

    if reply:
        add_to_cache("tipsy_words", reply)
        await tipsy_words.finish(
            "🍶 李太白给·借酒说话 🍶\n"
            f"{'='*22}\n"
            f"{reply}"
        )
    else:
        await tipsy_words.finish(random.choice(ERROR_MESSAGES))


# 今日心动
today_heartbeat = on_command("今日心动", aliases={"心动", "今天心动"}, priority=5, block=True)

@today_heartbeat.handle()
async def handle_today_heartbeat(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    nickname = await get_nickname(bot, user_id, context="今日心动")
    await today_heartbeat.finish(_render_today_heartbeat(nickname, current_date_text(), user_id))


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
3. 带一点李太白给式风流调侃，可爱但不要油腻
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

    reply = await call_api(prompt, system=ACROSTIC_SYSTEM_PROMPT)
    
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

