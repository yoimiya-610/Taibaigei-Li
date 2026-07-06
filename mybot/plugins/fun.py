import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from mybot.plugins.ai_cache import get_random_factors, build_random_prompt, add_to_cache
from mybot.common.ai_client import is_configured, prompt_completion
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.user_utils import get_nickname
from mybot.plugins.points import get_points, refund_points, spend_points


HELP_ITEMS = (
    HelpItem("趣味功能", "/骂我 - 文雅毒舌", 10),
    HelpItem("趣味功能", "/夸我 - 随机夸赞", 20),
    HelpItem("趣味功能", "/人生建议 - 随机人生建议", 30),
    HelpItem("趣味功能", "/今天吃什么 - 推荐今日饮食", 40),
    HelpItem("趣味功能", "/今天玩什么 - 推荐今日游戏", 50),
    HelpItem("趣味功能", "/发疯文学 主题 - 20积分", 60),
    HelpItem("趣味功能", "/废话文学 内容 - 20积分", 70),
    HelpItem("趣味功能", "/赛博算卦 问题 - 普通20/高级100积分", 80),
)
COMMAND_ALIASES = (
    "骂我", "骂",
    "夸我", "夸",
    "人生建议", "建议", "指点", "人生指点", "给个建议",
    "今天吃什么", "吃什么", "吃啥", "今天吃啥", "午饭吃什么", "晚饭吃什么",
    "今天玩什么", "玩什么", "玩啥", "今天玩啥", "玩点啥", "玩什么游戏",
    "发疯文学", "发疯", "疯话", "发癫", "疯一下",
    "废话文学", "废话", "废话扩写", "说废话",
    "赛博算卦", "算卦", "起卦", "算一卦", "占卜", "问卦",
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

FUN_TEXT_COST = 20
DIVINATION_NORMAL_COST = 20
DIVINATION_ADVANCED_COST = 100
MAX_FUN_TEXT_LENGTH = 80
MAX_DIVINATION_QUESTION_LENGTH = 80

logger = get_plugin_logger(__name__)

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

TRIGRAMS = {
    (1, 1, 1): {"name": "乾", "symbol": "☰", "image": "天", "virtue": "刚健", "advice": "宜主动开局，别只在心里挥剑。"},
    (1, 1, 0): {"name": "兑", "symbol": "☱", "image": "泽", "virtue": "悦纳", "advice": "宜把话说软，笑里藏一寸锋。"},
    (1, 0, 1): {"name": "离", "symbol": "☲", "image": "火", "virtue": "明丽", "advice": "宜先照清局面，再把热情点燃。"},
    (1, 0, 0): {"name": "震", "symbol": "☳", "image": "雷", "virtue": "发动", "advice": "宜动，但第一步要落得响亮又稳。"},
    (0, 1, 1): {"name": "巽", "symbol": "☴", "image": "风", "virtue": "入微", "advice": "宜迂回渗透，别硬撞南墙。"},
    (0, 1, 0): {"name": "坎", "symbol": "☵", "image": "水", "virtue": "险中求通", "advice": "宜留后路，涉水先看深浅。"},
    (0, 0, 1): {"name": "艮", "symbol": "☶", "image": "山", "virtue": "止定", "advice": "宜停一下，山不动时反而最有分量。"},
    (0, 0, 0): {"name": "坤", "symbol": "☷", "image": "地", "virtue": "承载", "advice": "宜稳住底盘，慢慢把事接牢。"},
}
HEXAGRAMS = {
    ("乾", "乾"): (1, "乾为天"),
    ("乾", "兑"): (10, "天泽履"),
    ("乾", "离"): (13, "天火同人"),
    ("乾", "震"): (25, "天雷无妄"),
    ("乾", "巽"): (44, "天风姤"),
    ("乾", "坎"): (6, "天水讼"),
    ("乾", "艮"): (33, "天山遁"),
    ("乾", "坤"): (12, "天地否"),
    ("兑", "乾"): (43, "泽天夬"),
    ("兑", "兑"): (58, "兑为泽"),
    ("兑", "离"): (49, "泽火革"),
    ("兑", "震"): (17, "泽雷随"),
    ("兑", "巽"): (28, "泽风大过"),
    ("兑", "坎"): (47, "泽水困"),
    ("兑", "艮"): (31, "泽山咸"),
    ("兑", "坤"): (45, "泽地萃"),
    ("离", "乾"): (14, "火天大有"),
    ("离", "兑"): (38, "火泽睽"),
    ("离", "离"): (30, "离为火"),
    ("离", "震"): (21, "火雷噬嗑"),
    ("离", "巽"): (50, "火风鼎"),
    ("离", "坎"): (64, "火水未济"),
    ("离", "艮"): (56, "火山旅"),
    ("离", "坤"): (35, "火地晋"),
    ("震", "乾"): (34, "雷天大壮"),
    ("震", "兑"): (54, "雷泽归妹"),
    ("震", "离"): (55, "雷火丰"),
    ("震", "震"): (51, "震为雷"),
    ("震", "巽"): (32, "雷风恒"),
    ("震", "坎"): (40, "雷水解"),
    ("震", "艮"): (62, "雷山小过"),
    ("震", "坤"): (16, "雷地豫"),
    ("巽", "乾"): (9, "风天小畜"),
    ("巽", "兑"): (61, "风泽中孚"),
    ("巽", "离"): (37, "风火家人"),
    ("巽", "震"): (42, "风雷益"),
    ("巽", "巽"): (57, "巽为风"),
    ("巽", "坎"): (59, "风水涣"),
    ("巽", "艮"): (53, "风山渐"),
    ("巽", "坤"): (20, "风地观"),
    ("坎", "乾"): (5, "水天需"),
    ("坎", "兑"): (60, "水泽节"),
    ("坎", "离"): (63, "水火既济"),
    ("坎", "震"): (3, "水雷屯"),
    ("坎", "巽"): (48, "水风井"),
    ("坎", "坎"): (29, "坎为水"),
    ("坎", "艮"): (39, "水山蹇"),
    ("坎", "坤"): (8, "水地比"),
    ("艮", "乾"): (26, "山天大畜"),
    ("艮", "兑"): (41, "山泽损"),
    ("艮", "离"): (22, "山火贲"),
    ("艮", "震"): (27, "山雷颐"),
    ("艮", "巽"): (18, "山风蛊"),
    ("艮", "坎"): (4, "山水蒙"),
    ("艮", "艮"): (52, "艮为山"),
    ("艮", "坤"): (23, "山地剥"),
    ("坤", "乾"): (11, "地天泰"),
    ("坤", "兑"): (19, "地泽临"),
    ("坤", "离"): (36, "地火明夷"),
    ("坤", "震"): (24, "地雷复"),
    ("坤", "巽"): (46, "地风升"),
    ("坤", "坎"): (7, "地水师"),
    ("坤", "艮"): (15, "地山谦"),
    ("坤", "坤"): (2, "坤为地"),
}
LINE_INFO = {
    6: {"name": "老阴", "mark": "⚋ ×", "changed": "变阳"},
    7: {"name": "少阳", "mark": "⚊", "changed": "不变"},
    8: {"name": "少阴", "mark": "⚋", "changed": "不变"},
    9: {"name": "老阳", "mark": "⚊ ○", "changed": "变阴"},
}
LINE_NAMES = ("初爻", "二爻", "三爻", "四爻", "五爻", "上爻")
QUICK_DIVINATION_LINES = (
    "此事像酒未温透，能做，但别急着一口闷。",
    "眼下有风，先顺势借力，硬拧容易把袖子扯坏。",
    "本猫看见一线亮处，先把小事做成，大事自然跟着开门。",
    "此问不宜逞强，宜藏锋三分，等对面先露破绽。",
    "吉里有忙，忙里有坑，带脑子上路便不算坏。",
    "今日卦气半醒半醉，答案是：可以试，但别押上全部家当。",
)
ADVANCED_PREFIXES = ("高级", "高阶", "周易", "严算", "详算", "认真算", "大算", "100")
NORMAL_PREFIXES = ("普通", "简算", "随便", "随便算", "20")
QUESTION_FOCUS_RULES = (
    (("摸鱼", "偷懒", "摆烂", "划水"), "偷闲摸鱼", "可偷一寸闲，别把整张桌子掀了。"),
    (("喜欢", "表白", "复合", "恋爱", "对象", "暧昧", "感情"), "情感", "心意可递半分，别一杯酒全泼出去。"),
    (("工作", "上班", "项目", "面试", "跳槽", "老板", "同事"), "事务", "先把眼前一件事钉牢，再谈大开大合。"),
    (("考试", "学习", "作业", "论文", "复习"), "学业", "临阵仍有可补之处，莫把书合得太早。"),
    (("钱", "买", "投资", "理财", "彩票", "抽卡", "消费"), "财事", "财上宜收着手，别把酒钱全押进风里。"),
    (("出门", "旅游", "约饭", "吃", "喝", "玩"), "出行玩乐", "可行但要留余地，别让兴致跑在鞋子前头。"),
    (("健康", "生病", "医院", "吃药", "疼", "病"), "身体", "此卦只作玩笑，真有不适还得听医嘱。"),
)


def _event_group_id(event: MessageEvent) -> str | None:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


def _build_mad_prompt(nickname: str, topic: str) -> str:
    return f"""用户"{nickname}"花了20积分，请你围绕主题"{topic}"写一段可发群聊的发疯文学。

要求：
1. 保持李太白给人设，自称本猫，有唐装、墨镜、酒壶的画面感
2. 情绪要夸张、抽象、好笑，但不能辱骂现实群友，不能露骨低俗
3. 主题必须贯穿全文，不要跑题
4. 180字以内，适合群聊直接发送
5. 结尾附带四句短诗，用『』包裹"""


def _build_nonsense_prompt(nickname: str, content: str) -> str:
    return f"""用户"{nickname}"花了20积分，请你把下面这句话扩写成华丽、认真、信息量很低的废话文学。

原句：
{content}

要求：
1. 不改变原句大意，只把它说得宏大、绕弯、很像一本正经的废话
2. 保持李太白给风味，自称本猫，可有动作旁白
3. 180字以内，适合群聊整活
4. 结尾附带四句短诗，用『』包裹"""


def parse_divination_request(raw_text: str) -> tuple[str, str, int]:
    text = raw_text.strip()
    for prefix in ADVANCED_PREFIXES:
        if text == prefix:
            return "advanced", "", DIVINATION_ADVANCED_COST
        if text.startswith(prefix + " "):
            return "advanced", text[len(prefix):].strip(), DIVINATION_ADVANCED_COST
    for prefix in NORMAL_PREFIXES:
        if text == prefix:
            return "normal", "", DIVINATION_NORMAL_COST
        if text.startswith(prefix + " "):
            return "normal", text[len(prefix):].strip(), DIVINATION_NORMAL_COST
    return "normal", text, DIVINATION_NORMAL_COST


def _draw_line(rng=random) -> dict:
    coins = tuple(rng.choice(("字", "背")) for _ in range(3))
    value = sum(2 if coin == "字" else 3 for coin in coins)
    info = LINE_INFO[value]
    return {
        "coins": coins,
        "value": value,
        "yin_yang": 1 if value in (7, 9) else 0,
        "changed_yin_yang": 0 if value == 9 else 1 if value == 6 else 1 if value == 7 else 0,
        "name": info["name"],
        "mark": info["mark"],
        "changed": info["changed"],
    }


def draw_hexagram(rng=random) -> dict:
    lines = [_draw_line(rng) for _ in range(6)]
    base_bits = tuple(line["yin_yang"] for line in lines)
    changed_bits = tuple(line["changed_yin_yang"] for line in lines)
    lower = TRIGRAMS[base_bits[:3]]
    upper = TRIGRAMS[base_bits[3:]]
    changed_lower = TRIGRAMS[changed_bits[:3]]
    changed_upper = TRIGRAMS[changed_bits[3:]]
    hex_number, hex_name = HEXAGRAMS[(upper["name"], lower["name"])]
    changed_number, changed_name = HEXAGRAMS[(changed_upper["name"], changed_lower["name"])]
    changing_lines = [index + 1 for index, line in enumerate(lines) if line["value"] in (6, 9)]
    return {
        "lines": lines,
        "lower": lower,
        "upper": upper,
        "changed_lower": changed_lower,
        "changed_upper": changed_upper,
        "hexagram": {"number": hex_number, "name": hex_name},
        "changed_hexagram": {"number": changed_number, "name": changed_name},
        "changing_lines": changing_lines,
    }


def _hexagram_title(hexagram: dict) -> str:
    return f"第{hexagram['number']}卦 {hexagram['name']}"


def _format_changing_lines(changing_lines: list[int]) -> str:
    if not changing_lines:
        return "无动爻，本卦主事，先守当前格局。"
    names = "、".join(LINE_NAMES[index - 1] for index in changing_lines)
    return f"动爻：{names}。动则有变，眼下不是死局。"


def _build_hexagram_advice(cast: dict, advanced: bool = False) -> str:
    upper = cast["upper"]
    lower = cast["lower"]
    changed = cast["changed_hexagram"]
    base = cast["hexagram"]
    direction = (
        f"上卦{upper['name']}为{upper['image']}，取{upper['virtue']}；"
        f"下卦{lower['name']}为{lower['image']}，取{lower['virtue']}。"
    )
    change_text = (
        f"若循动爻而变，去向是{_hexagram_title(changed)}。"
        if cast["changing_lines"]
        else "此卦无变，宜看本局，不必自己吓自己。"
    )
    if advanced:
        return (
            f"{direction}\n"
            f"本猫断曰：{_hexagram_title(base)}不是一句吉凶能说尽，先看势，再看人心。\n"
            f"{upper['advice']}{lower['advice']}\n"
            f"{change_text}"
        )
    return f"{direction}{change_text}"


def _question_focus(question: str) -> tuple[str, str]:
    for keywords, label, hint in QUESTION_FOCUS_RULES:
        if any(keyword in question for keyword in keywords):
            return label, hint
    return "此问", "先把目标说清，再让脚步跟上。"


def _hexagram_posture(cast: dict) -> str:
    yang_count = sum(line["yin_yang"] for line in cast["lines"])
    moving_count = len(cast["changing_lines"])
    if moving_count >= 4:
        return "局势正在翻面，先别一锤定音，等风向露出半个身子再动。"
    if moving_count == 0 and yang_count >= 4:
        return "势头偏顺，可试着推进，但别骄到把门槛当云梯。"
    if moving_count == 0 and yang_count <= 2:
        return "势头偏静，宜缓不宜莽，先守住手里的半盏酒。"
    if yang_count >= 4:
        return "偏向可行，适合主动一点，但最好先留后手。"
    if yang_count <= 2:
        return "偏向暂缓，能等则等，不能等也只宜小步试探。"
    return "吉凶未定，可小步试探，不宜一次把话说满。"


def _answer_question(question: str, cast: dict) -> str:
    focus, hint = _question_focus(question)
    return f"模糊回答：若问{focus}，本猫看是——{_hexagram_posture(cast)}{hint}"


def render_normal_divination(question: str, nickname: str, rng=random) -> str:
    cast = draw_hexagram(rng)
    quick = rng.choice(QUICK_DIVINATION_LINES)
    answer = _answer_question(question, cast)
    return (
        "🔮 李太白给·赛博算卦 🔮\n"
        f"{'='*22}\n"
        f"（晃了晃酒壶）{nickname} 问：{question}\n"
        f"档位：随便算算｜消耗 {DIVINATION_NORMAL_COST} 积分\n"
        f"{'='*22}\n"
        f"卦象：{_hexagram_title(cast['hexagram'])}\n"
        f"上下卦：{cast['upper']['symbol']}{cast['upper']['name']}上，{cast['lower']['symbol']}{cast['lower']['name']}下\n"
        f"{answer}\n"
        f"{quick}\n"
        f"{_build_hexagram_advice(cast)}\n"
        f"{'='*22}\n"
        "『卦在杯中浮半盏，\n"
        "吉凶且看脚边风。\n"
        "若能稳住三分气，\n"
        "坏事也能转小功。』"
    )


def render_advanced_divination(question: str, nickname: str, rng=random) -> str:
    cast = draw_hexagram(rng)
    answer = _answer_question(question, cast)
    line_rows = []
    for index, line in enumerate(cast["lines"]):
        coins = "".join(line["coins"])
        line_rows.append(
            f"{LINE_NAMES[index]}：{coins}={line['value']}，{line['name']} {line['mark']}，{line['changed']}"
        )
    process_text = "\n".join(line_rows)
    changed_text = (
        f"变卦：{_hexagram_title(cast['changed_hexagram'])}"
        if cast["changing_lines"]
        else "变卦：无动爻，不另成变卦"
    )
    return (
        "☯️ 李太白给·周易赛博算卦 ☯️\n"
        f"{'='*22}\n"
        f"（净手、扶镜、叩酒壶三声）{nickname} 问：{question}\n"
        f"档位：周易详算｜消耗 {DIVINATION_ADVANCED_COST} 积分\n"
        f"{'='*22}\n"
        f"起卦法：三枚铜钱起六爻，字=2，背=3；6为老阴，7为少阳，8为少阴，9为老阳。\n"
        f"{process_text}\n"
        f"{'='*22}\n"
        f"下卦：{cast['lower']['symbol']} {cast['lower']['name']}（{cast['lower']['image']}）\n"
        f"上卦：{cast['upper']['symbol']} {cast['upper']['name']}（{cast['upper']['image']}）\n"
        f"本卦：{_hexagram_title(cast['hexagram'])}\n"
        f"{_format_changing_lines(cast['changing_lines'])}\n"
        f"{changed_text}\n"
        f"{answer}\n"
        f"{'='*22}\n"
        f"{_build_hexagram_advice(cast, advanced=True)}\n"
        f"{'='*22}\n"
        "『六爻一落风雷定，\n"
        "八卦开时酒气清。\n"
        "莫把天机当铁券，\n"
        "还须人事补三分。』"
    )


def _insufficient_points_message(cost: int, current: int) -> str:
    return (
        f"（翻账本）这一回要 {cost} 积分，阁下账上只有 {current} 积分。\n"
        "『囊中先攒三分墨，来日再请本猫开坛。』"
    )


async def _charge_points_or_finish(matcher, event: MessageEvent, cost: int) -> tuple[str, str]:
    group_id = _event_group_id(event)
    if not group_id:
        await matcher.finish(
            "（合上账本）这类趣味开坛按群积分结算，请到群里再唤本猫。\n"
            "『独坐无账可相抵，群中一笑才成局。』"
        )
    user_id = event.get_user_id()
    points = get_points(user_id, group_id)
    if points["current"] < cost:
        await matcher.finish(_insufficient_points_message(cost, points["current"]))
    if not spend_points(user_id, group_id, cost):
        await matcher.finish(
            "（算盘一停）这笔积分暂时扣不上，请稍后再试。\n"
            "『账页偶逢风作乱，待墨痕干再开坛。』"
        )
    return user_id, group_id


async def call_api(prompt: str) -> str:
    """调用API，出错返回None"""
    return await prompt_completion(
        prompt,
        system=SYSTEM_PROMPT,
        max_tokens=500,
        temperature=0.95,
    )


# 发疯文学
mad_literature = on_command("发疯文学", aliases={"发疯", "疯话", "发癫", "疯一下"}, priority=5, block=True)

@mad_literature.handle()
async def handle_mad_literature(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    topic = args.extract_plain_text().strip()
    if not topic:
        await mad_literature.finish(
            "🤯 李太白给·发疯文学 🤯\n"
            f"{'='*22}\n"
            "用法：/发疯文学 主题\n"
            f"每次消耗 {FUN_TEXT_COST} 积分。\n"
            f"{'='*22}\n"
            "『题目递来酒半盏，本猫方敢乱云天。』"
        )
    if len(topic) > MAX_FUN_TEXT_LENGTH:
        await mad_literature.finish(
            f"（按住墨斗）主题太长，本猫会疯得找不着北。请压到 {MAX_FUN_TEXT_LENGTH} 字以内。\n"
            "『疯也须从一字起，长风莫把纸吹穿。』"
        )
    if not is_configured():
        await mad_literature.finish(
            "（揭开空墨盒）发疯炉今日没接上火，积分先替你留着。\n"
            "『疯诗且待炉中火，风来再写满屏花。』"
        )

    user_id, group_id = await _charge_points_or_finish(mad_literature, event, FUN_TEXT_COST)
    nickname = await get_nickname(bot, user_id, context="发疯文学")
    prompt = build_random_prompt(_build_mad_prompt(nickname, topic), get_random_factors())
    try:
        reply = await call_api(prompt)
        if not reply:
            raise RuntimeError("empty mad literature reply")
    except Exception as exc:
        refund_points(user_id, group_id, FUN_TEXT_COST)
        logger.exception(f"发疯文学生成失败 user_id={user_id} group_id={group_id}: {exc}")
        await mad_literature.finish(
            f"（抱住酒壶）这场疯没疯成，{FUN_TEXT_COST} 积分已原样退回。\n"
            "『狂云未起钱先返，待我醒来再发癫。』"
        )

    add_to_cache("mad_literature", reply)
    await mad_literature.finish(
        "🤯 李太白给·发疯文学 🤯\n"
        f"{'='*22}\n"
        f"主题：{topic}\n"
        f"（已收下 {FUN_TEXT_COST} 积分）\n"
        f"{'='*22}\n"
        f"{reply}"
    )


# 废话文学
nonsense_literature = on_command("废话文学", aliases={"废话", "废话扩写", "说废话"}, priority=5, block=True)

@nonsense_literature.handle()
async def handle_nonsense_literature(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    content = args.extract_plain_text().strip()
    if not content:
        await nonsense_literature.finish(
            "🌀 李太白给·废话文学 🌀\n"
            f"{'='*22}\n"
            "用法：/废话文学 内容\n"
            f"每次消耗 {FUN_TEXT_COST} 积分。\n"
            f"{'='*22}\n"
            "『一句白话入酒盏，本猫替你绕三山。』"
        )
    if len(content) > MAX_FUN_TEXT_LENGTH:
        await nonsense_literature.finish(
            f"（合上废话宝典）原句太长，再废就要成论文了。请压到 {MAX_FUN_TEXT_LENGTH} 字以内。\n"
            "『废话虽能绕千里，起笔仍须留一门。』"
        )
    if not is_configured():
        await nonsense_literature.finish(
            "（翻开空卷）废话炉今日没接上火，积分先替你留着。\n"
            "『空卷暂无云雾起，待灯明后再绕梁。』"
        )

    user_id, group_id = await _charge_points_or_finish(nonsense_literature, event, FUN_TEXT_COST)
    nickname = await get_nickname(bot, user_id, context="废话文学")
    prompt = build_random_prompt(_build_nonsense_prompt(nickname, content), get_random_factors())
    try:
        reply = await call_api(prompt)
        if not reply:
            raise RuntimeError("empty nonsense literature reply")
    except Exception as exc:
        refund_points(user_id, group_id, FUN_TEXT_COST)
        logger.exception(f"废话文学生成失败 user_id={user_id} group_id={group_id}: {exc}")
        await nonsense_literature.finish(
            f"（把废话卷轴收回袖中）这一段没绕成，{FUN_TEXT_COST} 积分已退回。\n"
            "『云绕半山终散去，钱回原处待新篇。』"
        )

    add_to_cache("nonsense_literature", reply)
    await nonsense_literature.finish(
        "🌀 李太白给·废话文学 🌀\n"
        f"{'='*22}\n"
        f"原句：{content}\n"
        f"（已收下 {FUN_TEXT_COST} 积分）\n"
        f"{'='*22}\n"
        f"{reply}"
    )


# 赛博算卦
cyber_divination = on_command("赛博算卦", aliases={"算卦", "起卦", "算一卦", "占卜", "问卦"}, priority=5, block=True)

@cyber_divination.handle()
async def handle_cyber_divination(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    tier, question, cost = parse_divination_request(args.extract_plain_text())
    if not question:
        await cyber_divination.finish(
            "🔮 李太白给·赛博算卦 🔮\n"
            f"{'='*22}\n"
            f"普通：/赛博算卦 问题（{DIVINATION_NORMAL_COST}积分，随便算算）\n"
            f"高级：/赛博算卦 高级 问题（{DIVINATION_ADVANCED_COST}积分，周易详算）\n"
            f"{'='*22}\n"
            "『卦无所问难成象，先把心事递杯前。』"
        )
    if len(question) > MAX_DIVINATION_QUESTION_LENGTH:
        await cyber_divination.finish(
            f"（收起铜钱）问题太长，卦盘装不下。请压到 {MAX_DIVINATION_QUESTION_LENGTH} 字以内。\n"
            "『一问须留一线明，话太繁时卦也昏。』"
        )

    user_id, _group_id = await _charge_points_or_finish(cyber_divination, event, cost)
    nickname = await get_nickname(bot, user_id, context="赛博算卦")
    if tier == "advanced":
        await cyber_divination.finish(render_advanced_divination(question, nickname))
    await cyber_divination.finish(render_normal_divination(question, nickname))


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
life_advice = on_command("人生建议", aliases={"建议", "指点", "人生指点", "给个建议"}, priority=5, block=True)

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
what_to_eat = on_command("今天吃什么", aliases={"吃什么", "吃啥", "今天吃啥", "午饭吃什么", "晚饭吃什么"}, priority=5, block=True)

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
what_to_play = on_command("今天玩什么", aliases={"玩什么", "玩啥", "今天玩啥", "玩点啥", "玩什么游戏"}, priority=5, block=True)

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

