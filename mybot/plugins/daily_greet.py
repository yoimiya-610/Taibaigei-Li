import random
from datetime import date

from nonebot import get_bot, require
from nonebot.adapters.onebot.v11 import Bot

from mybot.common.config import get_daily_greet_groups
from mybot.common.festival_calendar import generate_festival_schedule, get_festivals, three_year_window
from mybot.common.festival_greetings import get_festival_greeting
from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)

COMMAND_ALIASES = ("测试早安", "测试晚安", "节日表", "节气表")

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

# 早安问候词库
MORNING_GREETINGS = [
    # 正经问候
    "（伸懒腰）早安~新的一天开始了，愿诸位今日诸事顺遂~",
    "（推墨镜）早啊，睡眼惺忪的你，今天也很可爱呢~",
    "（端茶）晨起一杯茶，精神一整天。早安，各位~",
    "（打哈欠）太阳都晒屁股了，还不起床？早安~",
    "（抚须）日出东方，万物复苏。诸位早安~",
    "（晃酒壶）虽然本猫昨晚喝多了，但还是准时来问早安~",
    "（甩袖）闻鸡起舞的勇士们，早安！",
    "（递早餐）早起的鸟儿有虫吃，早起的猫猫有鱼吃。早安~",

    # 调侃问候
    "（敲窗）起床起床！上班的上班，搬砖的搬砖！",
    "（拉窗帘）阳光这么好，不起来晒晒太阳吗？早安~",
    "（掀被子）别睡了！再睡就中午了！",
    "（播放起床号）滴滴答滴滴答~起床啦！",
    "（端盆冷水）需要本猫帮你清醒一下吗？早安~",

    # 文艺问候
    "晨曦微露，万籁俱寂。愿你今日如朝阳般灿烂，早安~",
    "一日之计在于晨，愿诸位把握今朝，不负韶华。早安~",
    "春眠不觉晓，处处闻啼鸟。该起床啦，早安~",
    "云开雾散见天明，新的一天，新的开始。早安~",

    # 关心问候
    "早安~记得吃早餐哦，空腹伤胃~",
    "早安~今天也要元气满满地度过哦~",
    "早安~昨晚睡得好吗？今天也要加油~",
    "早安~出门记得看天气，别忘了带伞~",

    # 新增问候
    "（扶墨镜）天光已亮，诸位该把昨夜的梦，换成今朝的锋芒了。早安~",
    "（拎酒壶）本猫先敬晨风一口，再敬群友一声：早安，今日发达~",
    "（抖唐装）晨鼓已鸣，懒骨头们，该起身与命运过两招了~",
    "（趴窗台）太阳都来打卡了，你还在和枕头谈恋爱吗？早安~",
    "（递桂花糕）人间烟火最抚凡心，先吃早饭，再去征服世界。早安~",
    "（甩尾巴）本猫夜观星象，算出诸位今日宜顺利，忌摆烂。早安~",
    "（摇铃铛）早安早安，今日份好运已送达，请签收~",
    "（举扇）晨风不燥，阳光正好，适合起床，适合赚钱，也适合想本猫~",
    "（轻咳）昨夜诗酒风流，今朝依旧准时。诸位，早安且精神~",
    "（叼花枝）花会开，天会亮，群里的宝贝也该起床了。早安~",
    "（拍桌）别装死啦，生活已经开机，你也该上线了！",
    "（理衣襟）新的一页已经翻开，愿诸位今日落笔皆成锦。早安~",
    "（望天）朝霞都红成这样了，再不起，本猫可要写进诗里笑你了~",
    "（递热包子）江湖路远，先填肚子。早安，英雄们~",
    "（眯眼）今日的太阳很懂事，专程来照亮各位的前程。早安~",
    "（敲酒壶）本猫宣布：从现在开始，所有好运向本群集合。早安~",
]


# 早安诗句（20句）
MORNING_POEMS = [
    "『晨光落在瓦檐东，\n本猫提壶唤春风。\n诸君若肯今朝起，\n好运排队入门中~』",
    "『晓雾轻开见远空，\n群中诸位睡意浓。\n快将懒骨抖三抖，\n今日前程正向荣~』",
    "『鸡声一唱破帘栊，\n本猫墨镜照晴空。\n莫教被窝留壮志，\n起身便是第一功~』",
    "『朝霞一抹染云红，\n本猫敲窗唤睡虫。\n若问今晨宜做甚，\n宜把烦忧扫个空~』",
    "『东风吹醒小楼中，\n茶烟袅袅入帘栊。\n愿君今日多得意，\n一路轻舟一路风~』",
    "『天光渐暖鸟声匀，\n本猫提笔写清晨。\n不求万事皆如意，\n但求一步一生春~』",
    "『晨钟轻响过长街，\n本猫来把早安携。\n愿君今日眉常展，\n所行皆稳不曾歇~』",
    "『旭日初升照短墙，\n本猫今日又登场。\n诸位若能先起步，\n好运自然排成行~』",
    "『晓色分明过小窗，\n花枝带露送幽香。\n本猫先把晨安道，\n愿君今日不迷茫~』",
    "『红日一轮出海东，\n本猫醉里也从容。\n昨宵旧事随风去，\n今朝万象正葱茏~』",
    "『晨风翻动旧书章，\n本猫抖袖立廊旁。\n世间纵有千般事，\n先把精神养得强~』",
    "『朝云卷尽见天清，\n本猫唤你踏新程。\n莫嫌前路尘和远，\n一步一印自峥嵘~』",
    "『新阳才上柳梢轻，\n本猫先来报好晴。\n若把今日认真过，\n晚来回首也多情~』",
    "『晨露晶莹缀草青，\n群中豪杰莫还停。\n起身去把凡尘闯，\n衣上也能带月星~』",
    "『晓天微白雀初鸣，\n本猫倚栏酒半醒。\n愿你今日逢人喜，\n逢事平，逢路明~』",
    "『晨曦照面意先舒，\n本猫今日不含糊。\n先将早饭安顿好，\n再把乾坤慢慢图~』",
    "『云边金线破寒虚，\n本猫早起赋新句。\n愿君今日心头亮，\n不被闲愁绊半途~』",
    "『朝光满地草沾珠，\n本猫拂袖出江湖。\n群友若肯抬头看，\n处处皆成锦绣图~』",
    "『一城晨色入平芜，\n本猫叼花踏晓途。\n愿把人间清爽气，\n分君半缕去消枯~』",
    "『天边已见日轮苏，\n本猫在此唤群儒。\n新的一天开卷了，\n愿君下笔便鸿图~』",
]

# 晚安问候词库
NIGHT_GREETINGS = [
    # 正经问候
    "（打哈欠）夜深了，该休息了。晚安，好梦~",
    "（熄灯）月上柳梢头，该睡觉了。晚安~",
    "（盖被子）辛苦一天了，好好休息吧。晚安~",
    "（放轻音乐）让本猫为你播放一首安眠曲，晚安~",
    "（递热牛奶）睡前喝杯热牛奶，有助于睡眠哦。晚安~",
    "（关窗）夜风微凉，记得盖好被子。晚安~",
    "（调暗灯光）是时候放下手机了，晚安~",

    # 调侃问候
    "（没收手机）都几点了还不睡！明天不用上班吗！",
    "（敲门）隔壁都睡了，就你还在熬夜！",
    "（叹气）又要熬夜？你的黑眼圈都能当眼影了...",
    "（推墨镜）本猫都要睡了，你还不睡？",
    "（打哈欠）别肝了别肝了，身体要紧。晚安~",

    # 文艺问候
    "月明星稀，夜色如水。愿你今夜好梦，晚安~",
    "繁星点点，夜幕低垂。放下一天的疲惫，晚安~",
    "夜深人静，万籁俱寂。愿你枕着月光入眠，晚安~",
    "今宵多珍重，明朝再相逢。晚安，好梦~",

    # 关心问候
    "晚安~别熬夜，熬夜对皮肤不好哦~",
    "晚安~明天还要早起，快睡吧~",
    "晚安~今天辛苦了，好好休息~",
    "晚安~有什么烦心事，睡一觉就好了~",
    "晚安~记得定好闹钟，别睡过头~",

    # 新增问候
    "（收酒壶）今夜诗写到这里，诸位也该把眼睛合上了。晚安~",
    "（扶唐装）月亮已值夜班，本猫也来催诸位下线休息。晚安~",
    "（吹熄灯芯）白日的风尘先放一放，今夜只管好梦。晚安~",
    "（拢被角）外头风凉，心里别慌，先睡个好觉再说。晚安~",
    "（眯眼）别再刷啦，再刷天都要亮了。晚安，快睡~",
    "（抱尾巴）今天不容易，但你已经很棒了。晚安，好好歇~",
    "（倚窗）月色都替你铺好床了，还不肯赏脸去睡吗？晚安~",
    "（放下折扇）今夜无大事，唯一要事就是休息。晚安~",
    "（轻叹）白天拿命换碎银，夜里总该拿被窝疼自己。晚安~",
    "（递小毯子）先把烦恼打个包，明天再拆。晚安~",
    "（打响指）本猫宣布：从现在开始，禁止和床铺冷战。晚安~",
    "（摘墨镜）灯火该暗，眼眸该合，梦境该来。晚安~",
    "（拍枕头）床已经准备好了，就差你这位主角登场。晚安~",
    "（望月）今夜月色偏温柔，适合睡觉，也适合被世界轻轻抱一抱。晚安~",
    "（小声）别怕今天不圆满，睡醒又是新章节。晚安~",
    "（挥爪）群里的宝贝们，今晚就先把可爱收一收，早点睡。晚安~",
]

# 晚安诗句（20句）
NIGHT_POEMS = [
    "『月色轻铺上小窗，\n本猫提壶道晚凉。\n白日纷繁都放下，\n今宵只管入梦乡~』",
    "『星河缓缓过西楼，\n本猫敛袖劝君休。\n莫将心事熬成夜，\n且把疲惫付枕头~』",
    "『夜风吹过旧帘钩，\n灯影昏黄满小楼。\n今日辛酸皆可歇，\n明朝再把壮志收~』",
    "『月到中天影更柔，\n本猫前来送晚秋。\n不管白天赢与败，\n今宵都该好眠休~』",
    "『繁星一盏一盏明，\n本猫轻声道晚宁。\n愿你今宵无杂梦，\n只闻风静与虫鸣~』",
    "『夜色如绸覆小城，\n本猫倚栏酒半倾。\n愿君今夜身心稳，\n一觉醒来万事轻~』",
    "『窗前月白似银霜，\n本猫替你掩纱窗。\n把那烦忧关门外，\n留个好梦在身旁~』",
    "『长街灯火渐微黄，\n本猫催你早归床。\n人间纵有千般事，\n也要今宵养气长~』",
    "『夜深露冷草生香，\n本猫轻唤莫逞强。\n眼下先将身子顾，\n明朝才好闯八方~』",
    "『星子低垂月半廊，\n本猫抱尾坐西厢。\n愿你今晚睡得稳，\n梦里也有好时光~』",
    "『云间淡淡漏星辉，\n本猫关灯唤你归。\n世事纷纷明日论，\n今宵先与被窝偎~』",
    "『夜雨轻轻敲竹扉，\n本猫熄烛不多言。\n愿君心上无尖刺，\n枕梦安然到晓暾~』",
    "『月华如水浸罗帏，\n本猫今夜也知疲。\n诸君若肯先安寝，\n好梦自然不相违~』",
    "『银河斜挂过窗扉，\n尘念今宵可暂稀。\n本猫在此轻轻劝，\n收了辛劳便早归~』",
    "『灯火一层一层微，\n本猫轻步怕惊谁。\n愿君今夜身如羽，\n落进清梦不再飞~』",
    "『夜幕沉沉四野低，\n本猫抱壶倚短篱。\n不把愁肠长久煮，\n睡个踏实最相宜~』",
    "『月轮圆处照庭枝，\n本猫今夜也吟诗。\n愿你梦中逢好景，\n醒来眉眼尽欢时~』",
    "『更深人静漏声迟，\n本猫来把晚安题。\n明日山河仍在手，\n今宵先把旧愁辞~』",
    "『一缕清风过鬓丝，\n本猫轻语莫相思。\n若有烦忧难放下，\n且交长夜慢慢医~』",
    "『天边残月淡如脂，\n本猫收盏欲眠时。\n愿君此夜无惊梦，\n一枕安宁到晓曦~』",
]


def build_greeting_message(period: str, day: date | None = None) -> str:
    day = day or date.today()
    festivals = get_festivals(day)

    if period == "morning":
        icon = "🌅"
        label = "早安"
    elif period == "night":
        icon = "🌙"
        label = "晚安"
    else:
        raise ValueError(f"unsupported greeting period: {period}")

    if festivals:
        greeting, poem = get_festival_greeting(festivals[0], period)
        festival_names = "·".join(festival.name for festival in festivals)
        label = f"{festival_names}·{label}"
    elif period == "morning":
        greeting = random.choice(MORNING_GREETINGS)
        poem = random.choice(MORNING_POEMS)
    else:
        greeting = random.choice(NIGHT_GREETINGS)
        poem = random.choice(NIGHT_POEMS)

    return (
        f"{icon} 李太白给·{label} {icon}\n"
        f"{'='*20}\n"
        f"{greeting}\n"
        f"{'='*20}\n"
        f"{poem}"
    )


def render_festival_schedule(start: date | None = None) -> str:
    start, end = three_year_window(start)
    rows = generate_festival_schedule(start, end)
    lines = [
        "📅 李太白给·未来三年节日节气表 📅",
        "=" * 22,
        f"{start.isoformat()} 至 {end.isoformat()}",
        "节气日期按香港天文台公历农历对照表核定；不包含调休安排。",
        "=" * 22,
    ]
    current_year = None
    for festival_date, festival in rows:
        if festival_date.year != current_year:
            current_year = festival_date.year
            lines.append(f"\n【{current_year}年】")
        kind = "节气" if festival.category == "二十四节气" else "节日"
        lines.append(f"{festival_date.strftime('%m-%d')} [{kind}] {festival.name}")
    lines.extend(["=" * 22, "『岁时自有花开日，本猫按历候君安。』"])
    return "\n".join(lines)


# 早安定时任务
@scheduler.scheduled_job("cron", hour=8, minute=0, id="morning_greet")
async def morning_greet():
    try:
        bot: Bot = get_bot()
    except Exception as exc:
        logger.warning(f"早安定时任务获取 bot 失败: {exc}")
        return

    message = build_greeting_message("morning")
    
    for group_id in get_daily_greet_groups():
        try:
            await bot.send_group_msg(group_id=group_id, message=message)
        except Exception as exc:
            logger.exception(f"发送早安失败 group_id={group_id}: {exc}")

# 晚安定时任务
@scheduler.scheduled_job("cron", hour=0, minute=0, id="night_greet")
async def night_greet():
    try:
        bot: Bot = get_bot()
    except Exception as exc:
        logger.warning(f"晚安定时任务获取 bot 失败: {exc}")
        return

    message = build_greeting_message("night")
    
    for group_id in get_daily_greet_groups():
        try:
            await bot.send_group_msg(group_id=group_id, message=message)
        except Exception as exc:
            logger.exception(f"发送晚安失败 group_id={group_id}: {exc}")

# 测试命令
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

test_morning = on_command("测试早安", priority=5, block=True)
@test_morning.handle()
async def handle_test_morning(event: MessageEvent):
    await test_morning.finish(build_greeting_message("morning"))

test_night = on_command("测试晚安", priority=5, block=True)
@test_night.handle()
async def handle_test_night(event: MessageEvent):
    await test_night.finish(build_greeting_message("night"))


festival_schedule = on_command("节日表", aliases={"节气表"}, priority=5, block=True)


@festival_schedule.handle()
async def handle_festival_schedule():
    await festival_schedule.finish(render_festival_schedule())

