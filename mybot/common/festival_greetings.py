from dataclasses import dataclass

from mybot.common.festival_calendar import Festival


@dataclass(frozen=True)
class FestivalGreeting:
    morning: str
    night: str
    morning_poem: str
    night_poem: str


CELEBRATION_MORNING_POEM = "『佳节乘晨入画堂，\n一窗晴色一炉香。\n本猫先把吉言赠，\n愿你今朝福运长。』"
CELEBRATION_NIGHT_POEM = "『佳节灯深月满廊，\n人间欢意尚余香。\n本猫收盏催君睡，\n好梦随风到枕旁。』"
RESPECT_MORNING_POEM = "『晨风不语过长街，\n旧事于心未可埋。\n今日低声存敬意，\n清明一念照尘埃。』"
RESPECT_NIGHT_POEM = "『灯火低垂夜色深，\n山河无语记初心。\n今宵且把敬思寄，\n一寸清辉一寸心。』"


def _celebration(morning: str, night: str) -> FestivalGreeting:
    return FestivalGreeting(
        morning=morning,
        night=night,
        morning_poem=CELEBRATION_MORNING_POEM,
        night_poem=CELEBRATION_NIGHT_POEM,
    )


def _solar_term(name: str, morning: str, night: str) -> FestivalGreeting:
    return FestivalGreeting(
        morning=morning,
        night=night,
        morning_poem=(
            f"『{name}随风入晓窗，\n"
            "四时轮转各芬芳。\n"
            "本猫先把晨安送，\n"
            "愿你顺时身亦康。』"
        ),
        night_poem=(
            f"『{name}今宵过短廊，\n"
            "一庭节序一庭光。\n"
            "本猫收盏催君睡，\n"
            "梦与时和夜自长。』"
        ),
    )


FESTIVAL_GREETINGS = {
    "new_year": _celebration(
        "（翻开新历）元旦晨光已到，愿诸位新岁有新章，落笔皆顺遂。",
        "（合上新历）元旦的第一夜也该安歇了，愿新岁的好梦先来敲门。",
    ),
    "new_year_eve": _celebration(
        "（挂起红灯）除夕已至，愿诸位忙而不乱，早些归家围炉。",
        "（守着岁火）旧岁今宵辞去，愿诸位阖家安稳，好梦接新年。",
    ),
    "spring_festival": _celebration(
        "（披红唐装）春节早安！本猫给诸位拜年，愿新岁诸事兴旺。",
        "（收起拜年帖）春节夜深，愿红包有余、团圆常在，诸位好梦。",
    ),
    "lantern_festival": _celebration(
        "（挑起花灯）元宵晨安，愿诸位今日团团圆圆，所求皆明亮。",
        "（灯谜暂歇）花灯照夜，汤圆暖心，愿诸位元宵好梦。",
    ),
    "dragon_head": _celebration(
        "（替诸位抬头）二月二，龙抬头，愿今日精神抖擞、一路高走。",
        "（收起龙灯）龙抬头的好彩头已收下，今夜安心歇息，明日昂首再行。",
    ),
    "qingming": FestivalGreeting(
        morning="（放低声音）清明晨至，宜念故人，也宜珍惜眼前春光。",
        night="（拂去碑前尘）清明夜静，愿思念有所归处，生者平安珍重。",
        morning_poem=RESPECT_MORNING_POEM,
        night_poem=RESPECT_NIGHT_POEM,
    ),
    "dragon_boat": _celebration(
        "（系好五色绳）端午晨安，愿诸位安康顺意，今日粽有好味。",
        "（收起龙舟桨）端午夜深，愿艾香护梦，诸位平安入眠。",
    ),
    "qixi": _celebration(
        "（叼来一枝花）七夕晨安，愿真心都有回应，相伴不止今朝。",
        "（仰看鹊桥）七夕夜色正柔，愿有情人好梦相逢，无情人自在安眠。",
    ),
    "ghost_festival": FestivalGreeting(
        morning="（添一盏清茶）中元晨至，宜怀念、宜慎言，也宜把眼前人放在心上。",
        night="（掩好门窗）中元夜深，心存敬意便可安睡，愿诸位一夜平宁。",
        morning_poem=RESPECT_MORNING_POEM,
        night_poem=RESPECT_NIGHT_POEM,
    ),
    "mid_autumn": _celebration(
        "（托起一轮圆月）中秋晨安，愿诸位人圆事圆，所念皆在身边。",
        "（切好月饼）中秋月正明，愿团圆长久，今夜好梦也圆满。",
    ),
    "double_ninth": _celebration(
        "（登高望远）重阳晨安，愿家中长辈康健，也愿诸位步步高。",
        "（插好茱萸）重阳夜深，记得问候长辈，也记得让自己早些休息。",
    ),
    "laba": _celebration(
        "（端来腊八粥）腊八晨安，愿一碗热粥暖胃，新年的福气渐近。",
        "（温着粥锅）腊八夜寒，诸位早些安睡，暖意留到明晨。",
    ),
    "womens_day": _celebration(
        "（郑重作揖）妇女节晨安，愿每一位女性都自在坚定，被认真尊重。",
        "（奉上一枝花）今日辛劳暂且放下，愿诸位女性今夜安稳好梦。",
    ),
    "arbor_day": _celebration(
        "（扛起小锄）植树节晨安，愿今日种下的绿意，来日都成浓荫。",
        "（浇过新苗）树苗也歇了，诸位今夜早睡，明日继续生长。",
    ),
    "labor_day": _celebration(
        "（放下账本）劳动节晨安，辛劳的人今日值得歇一歇、乐一乐。",
        "（替诸位收工）劳动节夜深，愿所有奔忙都有回响，今夜好眠。",
    ),
    "youth_day": _celebration(
        "（迎着晨风）青年节晨安，愿心中有火、眼里有光，敢走远路。",
        "（收起远行图）青春不必一日燃尽，今夜先睡，明日再闯。",
    ),
    "childrens_day": _celebration(
        "（揣好糖果）儿童节晨安，愿大朋友小朋友今日都保留一点天真。",
        "（收好玩具）儿童节的快乐先放枕边，愿诸位梦里仍是少年。",
    ),
    "party_day": _celebration(
        "（正好衣襟）七一晨安，愿山河向前，诸位也守住心中方向。",
        "（望向灯火）七一夜深，愿初心长明，诸位安稳入眠。",
    ),
    "army_day": _celebration(
        "（端正敬礼）八一晨安，向守护山河的人致敬，愿岁月安宁。",
        "（放低声音）今夜灯火安稳，记得向守护平安的人道一声感谢。",
    ),
    "teachers_day": _celebration(
        "（铺开谢师帖）教师节晨安，愿传道授业者桃李芬芳，常得敬意。",
        "（合上教案）教师节夜深，愿辛勤的老师放下疲惫，安然好梦。",
    ),
    "martyrs_day": FestivalGreeting(
        morning="（摘下墨镜）烈士纪念日，今日当铭记来路，珍惜眼前山河。",
        night="（肃立片刻）夜色安宁，愿我们记得这份安宁从何而来。",
        morning_poem=RESPECT_MORNING_POEM,
        night_poem=RESPECT_NIGHT_POEM,
    ),
    "national_day": _celebration(
        "（展开山河卷）国庆晨安，愿家国安泰，也愿诸位假日舒心。",
        "（收起山河卷）国庆夜深，愿万家灯火安稳，诸位好梦绵长。",
    ),
    "memorial_day": FestivalGreeting(
        morning="（摘下墨镜）国家公祭日，今日不忘历史，珍重和平。",
        night="（静默片刻）愿逝者安息，愿和平长存，今夜心怀敬意而眠。",
        morning_poem=RESPECT_MORNING_POEM,
        night_poem=RESPECT_NIGHT_POEM,
    ),
    "mothers_day": _celebration(
        "（备好问候帖）母亲节晨安，记得向母亲道一声感谢与牵挂。",
        "（放轻脚步）母亲节夜深，愿天下母亲少些操劳，多些安眠。",
    ),
    "fathers_day": _celebration(
        "（斟上一杯茶）父亲节晨安，记得向父亲说句关心，不必等酒后。",
        "（收起茶盏）父亲节夜深，愿天下父亲卸下辛劳，安稳入梦。",
    ),
}

FESTIVAL_GREETINGS.update(
    {
        "solar_minor_cold": _solar_term(
            "小寒",
            "（拢紧唐装）小寒晨至，风虽冷，日子仍可过得热气腾腾。",
            "（添一块炭）小寒夜深，诸位记得保暖，早些钻进被窝。",
        ),
        "solar_major_cold": _solar_term(
            "大寒",
            "（哈出一团白气）大寒已至，岁末风紧，诸位添衣护身。",
            "（温好酒壶）大寒夜里最宜安睡，愿一床暖意护你到天明。",
        ),
        "solar_start_spring": _solar_term(
            "立春",
            "（折来一枝新柳）今日立春，愿诸位从此迎风生长，万事新鲜。",
            "（听风过檐）立春夜里已有新意，愿好梦先替你走进春天。",
        ),
        "solar_rain_water": _solar_term(
            "雨水",
            "（接住檐前细雨）雨水润物，愿诸位今日心田也有新绿。",
            "（合好纸伞）雨水夜静，愿细雨洗去疲惫，诸位安眠。",
        ),
        "solar_awakening_insects": _solar_term(
            "惊蛰",
            "（敲响一声春雷）惊蛰晨至，沉睡的志气也该醒一醒了。",
            "（收起春雷）惊蛰夜深，万物已醒，诸位却该安心睡了。",
        ),
        "solar_spring_equinox": _solar_term(
            "春分",
            "（量了量昼夜）春分已至，昼夜均平，愿诸位心中也从容平衡。",
            "（看月过中庭）春分夜静，冷暖恰好，愿诸位一梦安稳。",
        ),
        "solar_qingming": _solar_term(
            "清明",
            "（望向杏花春雨）清明节气已至，宜念来路，也宜珍惜新生。",
            "（放低灯火）清明夜色清静，愿思念有归处，诸位皆珍重。",
        ),
        "solar_grain_rain": _solar_term(
            "谷雨",
            "（看雨落新苗）谷雨生百谷，愿今日耕耘都能等到收成。",
            "（听一夜春雨）谷雨夜润，愿诸位放下忙碌，安稳入眠。",
        ),
        "solar_start_summer": _solar_term(
            "立夏",
            "（换上轻衫）立夏晨至，草木正盛，愿诸位也精神蓬勃。",
            "（摇起蒲扇）立夏夜暖，愿晚风送凉，诸位好梦悠长。",
        ),
        "solar_grain_buds": _solar_term(
            "小满",
            "（看麦穗初满）小满未满，恰是从容，愿诸位知足也知进。",
            "（收好半卷诗）小满夜深，不求事事盈满，只求今夜安眠。",
        ),
        "solar_grain_in_ear": _solar_term(
            "芒种",
            "（卷起衣袖）芒种忙种，愿诸位所播皆有所得，忙而不乱。",
            "（放下农具）芒种夜里也该歇息，明日才有力气继续耕耘。",
        ),
        "solar_summer_solstice": _solar_term(
            "夏至",
            "（迎着最长日光）夏至晨安，愿诸位心有清凉，步履明亮。",
            "（摇扇看星）夏至夜短，更该早些入眠，莫与暑气硬撑。",
        ),
        "solar_minor_heat": _solar_term(
            "小暑",
            "（递来一盏凉茶）小暑已至，愿诸位忙中避热，心静身安。",
            "（把凉席铺好）小暑夜暖，少些熬夜，多些清凉好梦。",
        ),
        "solar_major_heat": _solar_term(
            "大暑",
            "（躲进竹帘阴影）大暑晨至，诸位记得防晒补水，莫逞强。",
            "（添满凉茶）大暑夜里暑气未消，愿清风护你安眠。",
        ),
        "solar_start_autumn": _solar_term(
            "立秋",
            "（接住第一片秋意）今日立秋，愿收获渐近，烦热渐远。",
            "（听秋风叩窗）立秋夜里已有凉意，诸位记得添被好眠。",
        ),
        "solar_end_heat": _solar_term(
            "处暑",
            "（送走暑气）处暑晨至，炎热渐退，愿诸位身心清爽。",
            "（合起蒲扇）处暑夜凉，最宜安睡，愿诸位梦里无燥。",
        ),
        "solar_white_dew": _solar_term(
            "白露",
            "（看草叶凝露）白露晨至，秋意渐浓，诸位记得早晚添衣。",
            "（掩好薄窗）白露夜凉，愿一床暖被护诸位到晨光。",
        ),
        "solar_autumn_equinox": _solar_term(
            "秋分",
            "（分好一半秋色）秋分已至，昼夜相均，愿诸位收获从容。",
            "（看月平分夜色）秋分夜静，愿心事也寻得恰好的分寸。",
        ),
        "solar_cold_dew": _solar_term(
            "寒露",
            "（拂去衣上寒露）寒露晨至，凉意入骨，诸位务必添衣。",
            "（温起一壶热茶）寒露夜深，愿暖意入梦，诸位安眠。",
        ),
        "solar_frost_descent": _solar_term(
            "霜降",
            "（看瓦上初霜）霜降晨至，秋色将尽，愿诸位安暖无恙。",
            "（关好窗扉）霜降夜寒，莫让冷风偷走好梦。",
        ),
        "solar_start_winter": _solar_term(
            "立冬",
            "（围好围巾）今日立冬，愿诸位藏好精神，也攒足温暖。",
            "（煨着冬夜炉火）立冬夜长，愿诸位早眠，梦中常暖。",
        ),
        "solar_minor_snow": _solar_term(
            "小雪",
            "（伸爪接雪）小雪晨至，寒意渐深，愿诸位步稳衣暖。",
            "（扫去肩头薄雪）小雪夜静，愿被窝温暖，好梦轻落。",
        ),
        "solar_major_snow": _solar_term(
            "大雪",
            "（推门看雪）大雪晨至，天地清白，诸位出门注意脚下。",
            "（围炉听雪）大雪夜深，愿风雪止于窗外，暖梦留在枕边。",
        ),
        "solar_winter_solstice": _solar_term(
            "冬至",
            "（端来一碗热汤）冬至晨安，愿团圆有期，寒冬有暖。",
            "（数着长夜灯火）冬至夜最长，诸位早些安睡，静候阳生。",
        ),
    }
)


def get_festival_greeting(festival: Festival, period: str) -> tuple[str, str]:
    profile = FESTIVAL_GREETINGS[festival.key]
    if period == "morning":
        return profile.morning, profile.morning_poem
    if period == "night":
        return profile.night, profile.night_poem
    raise ValueError(f"unsupported greeting period: {period}")
