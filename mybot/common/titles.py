from dataclasses import dataclass
from datetime import date, datetime, timedelta
from calendar import monthrange
from pathlib import Path

from common.charm import get_charm
from common.interaction_stats import get_auto_reply_trigger_count
from common.json_store import load_json, mutate_json
from common.streak import get_current_streak


BOT_ROOT = Path(__file__).resolve().parent.parent
TITLE_DATA_FILE = BOT_ROOT / "data" / "titles.json"
CLASSICS_FILE = BOT_ROOT / "data" / "classics.json"
FORTUNE_FILE = BOT_ROOT / "data" / "fortune_data.json"
MONTHLY_FAME_FILE = BOT_ROOT / "data" / "monthly_fame.json"
DEFAULT_TITLE_DATA = {"users": {}}


@dataclass(frozen=True)
class TitleAchievement:
    id: str
    title: str
    category: str
    name: str
    metric: str
    threshold: int
    description: str
    order: int
    hidden: bool = False


DEFAULT_TITLE = TitleAchievement(
    id="default",
    title="初入诗门",
    category="初始",
    name="初入诗门",
    metric="always",
    threshold=0,
    description="初见本猫，已算半个诗门中人。",
    order=0,
)


ACHIEVEMENTS = (
    TitleAchievement("points_1000", "斗酒诗百篇", "积分", "累计千分", "total_points", 1000, "累计获得 1000 积分", 1010),
    TitleAchievement("points_5000", "长风破浪士", "积分", "五千长风", "total_points", 5000, "累计获得 5000 积分", 1020),
    TitleAchievement("points_10000", "明月举杯客", "积分", "万分明月", "total_points", 10000, "累计获得 10000 积分", 1030),
    TitleAchievement("points_20000", "云帆济海人", "积分", "两万云帆", "total_points", 20000, "累计获得 20000 积分", 1040),
    TitleAchievement("points_50000", "青莲剑歌客", "积分", "五万青莲", "total_points", 50000, "累计获得 50000 积分", 1050),
    TitleAchievement("points_100000", "谪仙诗圣", "积分", "十万谪仙", "total_points", 100000, "累计获得 100000 积分", 1060),
    TitleAchievement("streak_3", "三日添墨人", "签到", "三日添墨", "streak", 3, "连续签到 3 天", 2005),
    TitleAchievement("streak_7", "晨钟七响客", "签到", "七日连签", "streak", 7, "连续签到 7 天", 2010),
    TitleAchievement("streak_14", "半月不眠灯", "签到", "半月不辍", "streak", 14, "连续签到 14 天", 2015),
    TitleAchievement("streak_30", "一月不辍客", "签到", "一月不辍", "streak", 30, "连续签到 30 天", 2020),
    TitleAchievement("streak_60", "双月守签人", "签到", "双月守签", "streak", 60, "连续签到 60 天", 2025),
    TitleAchievement("streak_100", "百日长明灯", "签到", "百日长明", "streak", 100, "连续签到 100 天", 2030),
    TitleAchievement("streak_180", "半岁长青客", "签到", "半岁长青", "streak", 180, "连续签到 180 天", 2035),
    TitleAchievement("streak_365", "岁岁不辍人", "签到", "岁岁不辍", "streak", 365, "连续签到 365 天", 2040),
    TitleAchievement("fortune_destiny_1", "天命初临客", "签运", "一遇天命", "fortune_destiny_count", 1, "累计抽到天命之子 1 次", 2510),
    TitleAchievement("fortune_destiny_3", "紫微照命人", "签运", "三遇天命", "fortune_destiny_count", 3, "累计抽到天命之子 3 次", 2520),
    TitleAchievement("fortune_destiny_10", "天命所归君", "签运", "十遇天命", "fortune_destiny_count", 10, "累计抽到天命之子 10 次", 2530),
    TitleAchievement("fortune_great_bad_1", "大凶生还者", "签运", "一过大凶", "fortune_great_bad_count", 1, "累计抽到大凶 1 次", 2610),
    TitleAchievement("fortune_great_bad_5", "逆风提灯人", "签运", "五过大凶", "fortune_great_bad_count", 5, "累计抽到大凶 5 次", 2620),
    TitleAchievement("fortune_great_bad_20", "凶签不倒翁", "签运", "二十凶签", "fortune_great_bad_count", 20, "累计抽到大凶 20 次", 2630),
    TitleAchievement("fortune_unknown", "气运之神", "签运", "气运之神", "fortune_unknown_count", 1, "签逢？？？", 2700, True),
    TitleAchievement("charm_50", "花间初逢客", "魅力", "花间初逢", "charm", 50, "魅力值达到 50", 3010),
    TitleAchievement("charm_100", "月下留香客", "魅力", "月下留香", "charm", 100, "魅力值达到 100", 3020),
    TitleAchievement("charm_200", "袖底生香客", "魅力", "袖底生香", "charm", 200, "魅力值达到 200", 3025),
    TitleAchievement("charm_300", "群中玉树郎", "魅力", "群中玉树", "charm", 300, "魅力值达到 300", 3030),
    TitleAchievement("charm_500", "满屏花信使", "魅力", "满屏花信", "charm", 500, "魅力值达到 500", 3035),
    TitleAchievement("charm_1000", "满座春风主", "魅力", "满座春风", "charm", 1000, "魅力值达到 1000", 3040),
    TitleAchievement("auto_reply_1", "一语惊猫客", "自动回话", "一语惊猫", "auto_reply_count", 1, "触发自动回话 1 次", 3510),
    TitleAchievement("auto_reply_10", "群风唤猫人", "自动回话", "十次唤猫", "auto_reply_count", 10, "触发自动回话 10 次", 3520),
    TitleAchievement("auto_reply_50", "太白常顾客", "自动回话", "五十回眸", "auto_reply_count", 50, "触发自动回话 50 次", 3530),
    TitleAchievement("auto_reply_200", "本猫座上宾", "自动回话", "二百应声", "auto_reply_count", 200, "触发自动回话 200 次", 3540),
    TitleAchievement("quote_speaker_1", "片言入卷人", "入典", "一言入典", "quote_speaker_count", 1, "本人语录被入典 1 条", 4010),
    TitleAchievement("quote_speaker_5", "群典常客", "入典", "五入群典", "quote_speaker_count", 5, "本人语录被入典 5 条", 4020),
    TitleAchievement("quote_speaker_10", "金句频出客", "入典", "十句入典", "quote_speaker_count", 10, "本人语录被入典 10 条", 4025),
    TitleAchievement("quote_speaker_20", "典藏名士", "入典", "二十典藏", "quote_speaker_count", 20, "本人语录被入典 20 条", 4030),
    TitleAchievement("quote_speaker_50", "群典活卷宗", "入典", "五十典藏", "quote_speaker_count", 50, "本人语录被入典 50 条", 4040),
    TitleAchievement("quote_recorder_5", "执笔小史官", "执笔", "五次执笔", "quote_recorder_count", 5, "亲手收录语录 5 条", 5010),
    TitleAchievement("quote_recorder_10", "摘句校书郎", "执笔", "十次摘句", "quote_recorder_count", 10, "亲手收录语录 10 条", 5015),
    TitleAchievement("quote_recorder_20", "群史修撰官", "执笔", "二十修撰", "quote_recorder_count", 20, "亲手收录语录 20 条", 5020),
    TitleAchievement("quote_recorder_50", "掌典大学士", "执笔", "五十掌典", "quote_recorder_count", 50, "亲手收录语录 50 条", 5030),
    TitleAchievement("monthly_fame_first", "月榜风云魁首", "风云榜", "风云魁首", "monthly_fame_awards", 1, "登上月度风云榜榜首", 6010),
    TitleAchievement("monthly_fame_second", "月榜凌云客", "风云榜", "凌云次席", "monthly_fame_awards", 1, "登上月度风云榜第二名", 6020),
    TitleAchievement("monthly_fame_third", "月榜探花郎", "风云榜", "风月探花", "monthly_fame_awards", 1, "登上月度风云榜第三名", 6030),
    TitleAchievement("secret_fortune_reversal", "否极星回", "秘闻", "凶后星回", "fortune_reversal_count", 1, "大凶翌日再逢天命", 9010, True),
    TitleAchievement("secret_double_destiny", "双曜照命", "秘闻", "双曜照命", "fortune_double_destiny_count", 1, "连日抽到天命之子", 9020, True),
    TitleAchievement("secret_fortune_triad", "命书执笔人", "秘闻", "三象同阅", "fortune_extreme_triad", 1, "见过大凶、天命与？？？", 9030, True),
    TitleAchievement("secret_full_month", "月满无缺", "秘闻", "月满无缺", "native_full_month_count", 1, "完整自然月每日亲签", 9040, True),
    TitleAchievement("secret_midnight_recorder", "子夜校书人", "秘闻", "子夜校书", "midnight_quote_count", 1, "子夜时分收录语录", 9050, True),
    TitleAchievement("secret_quote_dual", "卷中卷外人", "秘闻", "卷中卷外", "quote_dual_role", 1, "既被入典，也曾执笔", 9060, True),
    TitleAchievement("secret_charm_resonance", "群星应答人", "秘闻", "群星应答", "charm_reply_resonance", 1, "魅力与应答共鸣", 9070, True),
    TitleAchievement("secret_fame_podium", "三台同登者", "秘闻", "三台同登", "monthly_fame_podium_count", 3, "分别登上月榜前三席", 9080, True),
    TitleAchievement("secret_fame_three_firsts", "三月风云主", "秘闻", "三月魁首", "monthly_fame_first_count", 3, "三次登临月榜榜首", 9090, True),
)

ALL_TITLES = (DEFAULT_TITLE,) + ACHIEVEMENTS
TITLE_BY_ID = {achievement.id: achievement for achievement in ALL_TITLES}
POINT_TITLE_IDS = {
    achievement.id
    for achievement in ACHIEVEMENTS
    if achievement.category == "积分"
}


def _title_key(group_id: str, user_id: str) -> str:
    return f"{group_id}_{user_id}"


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _quote_counts(user_id: str, group_id: str) -> tuple[int, int]:
    data = load_json(CLASSICS_FILE, {"groups": {}})
    group = data.get("groups", {}).get(group_id, {})
    classics = group.get("classics", {})
    if not isinstance(classics, dict):
        return 0, 0

    speaker_count = 0
    recorder_count = 0
    for speaker_id, records in classics.items():
        if not isinstance(records, list):
            continue
        if str(speaker_id) == user_id:
            speaker_count += len(records)
        for record in records:
            if isinstance(record, dict) and str(record.get("recorder_id")) == user_id:
                recorder_count += 1
    return speaker_count, recorder_count


def _legacy_fortune_record_belongs_to_user(record_key: str, user_id: str) -> bool:
    parts = record_key.split("_")
    return len(parts) == 2 and parts[-1] == user_id


def _group_fortune_record_belongs_to_user(record_key: str, user_id: str, group_id: str) -> bool:
    parts = record_key.split("_")
    return len(parts) >= 3 and parts[-2] == group_id and parts[-1] == user_id


def _fortune_counts(user_id: str, group_id: str) -> tuple[int, int, int]:
    data = load_json(FORTUNE_FILE, {"fortune_record": {}})
    records = data.get("fortune_record", {})
    if not isinstance(records, dict):
        return 0, 0, 0

    destiny_count = 0
    great_bad_count = 0
    unknown_count = 0
    for record_key, record in records.items():
        if not isinstance(record, dict):
            continue
        if not (
            _group_fortune_record_belongs_to_user(str(record_key), user_id, group_id)
            or _legacy_fortune_record_belongs_to_user(str(record_key), user_id)
        ):
            continue
        fortune = str(record.get("fortune", ""))
        if fortune == "？？？":
            unknown_count += 1
        elif fortune == "天命之子":
            destiny_count += 1
        elif fortune == "大凶":
            great_bad_count += 1
    return destiny_count, great_bad_count, unknown_count


def _fortune_easter_egg_metrics(user_id: str, group_id: str) -> dict[str, int]:
    data = load_json(FORTUNE_FILE, {"fortune_record": {}})
    records = data.get("fortune_record", {})
    if not isinstance(records, dict):
        return {
            "fortune_reversal_count": 0,
            "fortune_double_destiny_count": 0,
            "fortune_extreme_triad": 0,
            "native_full_month_count": 0,
        }

    fortunes_by_date: dict[date, str] = {}
    for record_key, record in records.items():
        if not isinstance(record, dict):
            continue

        key_text = str(record_key)
        parts = key_text.split("_")
        if _group_fortune_record_belongs_to_user(key_text, user_id, group_id):
            date_text = "_".join(parts[:-2])
        elif _legacy_fortune_record_belongs_to_user(key_text, user_id):
            date_text = parts[0]
        else:
            continue

        try:
            record_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        fortunes_by_date[record_date] = str(record.get("fortune", ""))

    reversal_count = sum(
        1
        for record_date, fortune in fortunes_by_date.items()
        if fortune == "大凶" and fortunes_by_date.get(record_date + timedelta(days=1)) == "天命之子"
    )
    double_destiny_count = sum(
        1
        for record_date, fortune in fortunes_by_date.items()
        if fortune == "天命之子" and fortunes_by_date.get(record_date + timedelta(days=1)) == "天命之子"
    )
    encountered = set(fortunes_by_date.values())

    signed_months: dict[tuple[int, int], set[int]] = {}
    current_month = (datetime.now().year, datetime.now().month)
    for record_date in fortunes_by_date:
        month_key = (record_date.year, record_date.month)
        if month_key >= current_month:
            continue
        signed_months.setdefault(month_key, set()).add(record_date.day)
    native_full_month_count = sum(
        1
        for (year, month), days in signed_months.items()
        if len(days) == monthrange(year, month)[1]
    )

    return {
        "fortune_reversal_count": reversal_count,
        "fortune_double_destiny_count": double_destiny_count,
        "fortune_extreme_triad": int({"大凶", "天命之子", "？？？"}.issubset(encountered)),
        "native_full_month_count": native_full_month_count,
    }


def _quote_easter_egg_metrics(user_id: str, group_id: str) -> dict[str, int]:
    data = load_json(CLASSICS_FILE, {"groups": {}})
    group = data.get("groups", {}).get(group_id, {})
    classics = group.get("classics", {})
    if not isinstance(classics, dict):
        return {"midnight_quote_count": 0, "quote_dual_role": 0}

    speaker_count = 0
    recorder_count = 0
    midnight_count = 0
    for speaker_id, records in classics.items():
        if not isinstance(records, list):
            continue
        if str(speaker_id) == user_id:
            speaker_count += len(records)
        for record in records:
            if not isinstance(record, dict) or str(record.get("recorder_id")) != user_id:
                continue
            recorder_count += 1
            try:
                recorded_at = datetime.fromtimestamp(float(record.get("recorded_timestamp")))
            except (TypeError, ValueError, OSError):
                continue
            if 0 <= recorded_at.hour < 5:
                midnight_count += 1

    return {
        "midnight_quote_count": midnight_count,
        "quote_dual_role": int(speaker_count > 0 and recorder_count > 0),
    }


def _monthly_fame_easter_egg_metrics(user_id: str, group_id: str) -> dict[str, int]:
    data = load_json(MONTHLY_FAME_FILE, {"groups": {}})
    group = data.get("groups", {}).get(group_id, {})
    if not isinstance(group, dict):
        return {"monthly_fame_podium_count": 0, "monthly_fame_first_count": 0}

    ranks: set[int] = set()
    first_count = 0
    for settlement in group.values():
        if not isinstance(settlement, dict):
            continue
        awards = settlement.get("awards", [])
        if not isinstance(awards, list):
            continue
        for award in awards:
            if not isinstance(award, dict) or str(award.get("user_id")) != user_id:
                continue
            rank = _safe_int(award.get("rank"))
            if rank in {1, 2, 3}:
                ranks.add(rank)
            if rank == 1:
                first_count += 1

    return {
        "monthly_fame_podium_count": len(ranks),
        "monthly_fame_first_count": first_count,
    }


def collect_title_metrics(user_id: str, group_id: str, points_info: dict | None = None) -> dict[str, int]:
    points_info = points_info or {}
    quote_speaker_count, quote_recorder_count = _quote_counts(user_id, group_id)
    destiny_count, great_bad_count, unknown_count = _fortune_counts(user_id, group_id)
    metrics = {
        "always": 0,
        "current_points": _safe_int(points_info.get("current", 0)),
        "total_points": _safe_int(points_info.get("total", 0)),
        "streak": get_current_streak(user_id, group_id),
        "charm": get_charm(user_id, group_id),
        "auto_reply_count": get_auto_reply_trigger_count(user_id, group_id),
        "fortune_destiny_count": destiny_count,
        "fortune_great_bad_count": great_bad_count,
        "fortune_unknown_count": unknown_count,
        "quote_speaker_count": quote_speaker_count,
        "quote_recorder_count": quote_recorder_count,
    }
    metrics.update(_fortune_easter_egg_metrics(user_id, group_id))
    metrics.update(_quote_easter_egg_metrics(user_id, group_id))
    metrics.update(_monthly_fame_easter_egg_metrics(user_id, group_id))
    metrics["charm_reply_resonance"] = int(
        metrics["charm"] >= 500 and metrics["auto_reply_count"] >= 50
    )
    return metrics


def _sort_title_ids(title_ids: set[str] | list[str]) -> list[str]:
    valid_ids = [title_id for title_id in title_ids if title_id in TITLE_BY_ID]
    return sorted(valid_ids, key=lambda title_id: (TITLE_BY_ID[title_id].order, TITLE_BY_ID[title_id].title))


def _achieved_title_ids(metrics: dict[str, int]) -> set[str]:
    achieved = {"default"}
    for achievement in ACHIEVEMENTS:
        if metrics.get(achievement.metric, 0) >= achievement.threshold:
            achieved.add(achievement.id)
    return achieved


def sync_user_titles(user_id: str, group_id: str, points_info: dict | None = None) -> dict:
    metrics = collect_title_metrics(user_id, group_id, points_info)
    achieved_ids = _achieved_title_ids(metrics)
    key = _title_key(group_id, user_id)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mutator(data: dict) -> dict:
        users = data.setdefault("users", {})
        existed = key in users
        record = users.setdefault(
            key,
            {
                "user_id": user_id,
                "group_id": group_id,
                "unlocked": ["default"],
                "equipped": "",
                "updated_at": now_text,
            },
        )
        old_unlocked = set(record.get("unlocked", [])) | {"default"}
        unlocked = old_unlocked | achieved_ids
        equipped = str(record.get("equipped", ""))
        equipped_invalid = bool(equipped and equipped not in unlocked)
        if equipped and equipped not in unlocked:
            record["equipped"] = ""
        record["unlocked"] = _sort_title_ids(unlocked)
        if not existed or unlocked != old_unlocked or equipped_invalid:
            record["updated_at"] = now_text
        return {
            "record": dict(record),
            "metrics": dict(metrics),
            "new_ids": _sort_title_ids(achieved_ids - old_unlocked),
        }

    return mutate_json(TITLE_DATA_FILE, DEFAULT_TITLE_DATA, mutator)


def _auto_title_id(unlocked_ids: list[str]) -> str:
    point_ids = [title_id for title_id in unlocked_ids if title_id in POINT_TITLE_IDS]
    if point_ids:
        return max(point_ids, key=lambda title_id: TITLE_BY_ID[title_id].threshold)
    return "default"


def _visible_title_ids(unlocked_ids: set[str]) -> list[str]:
    return [
        achievement.id
        for achievement in ALL_TITLES
        if not achievement.hidden or achievement.id in unlocked_ids
    ]


def get_display_title(user_id: str, group_id: str, points_info: dict | None = None) -> dict:
    status = sync_user_titles(user_id, group_id, points_info)
    record = status["record"]
    unlocked_ids = record.get("unlocked", ["default"])
    unlocked_set = set(unlocked_ids)
    visible_title_ids = set(_visible_title_ids(unlocked_set))
    equipped_id = str(record.get("equipped", ""))
    manual = equipped_id in unlocked_ids and equipped_id in TITLE_BY_ID
    title_id = equipped_id if manual else _auto_title_id(unlocked_ids)
    achievement = TITLE_BY_ID.get(title_id, DEFAULT_TITLE)
    return {
        "title": achievement.title,
        "title_id": achievement.id,
        "manual": manual,
        "unlocked_count": len([title_id for title_id in unlocked_ids if title_id in visible_title_ids]),
        "total_count": len(visible_title_ids),
        "new_ids": status["new_ids"],
        "new_titles": [TITLE_BY_ID[title_id].title for title_id in status["new_ids"]],
    }


def _resolve_unlocked_identifier(identifier: str, unlocked_ids: list[str]) -> str | None:
    text = identifier.strip()
    if not text:
        return None
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(unlocked_ids):
            return unlocked_ids[index]
        return None

    normalized = text.lower()
    for title_id in unlocked_ids:
        achievement = TITLE_BY_ID[title_id]
        candidates = {achievement.id.lower(), achievement.title.lower(), achievement.name.lower()}
        if normalized in candidates:
            return title_id
    return None


def equip_title(user_id: str, group_id: str, identifier: str, points_info: dict | None = None) -> TitleAchievement | None:
    status = sync_user_titles(user_id, group_id, points_info)
    unlocked_ids = status["record"].get("unlocked", ["default"])
    title_id = _resolve_unlocked_identifier(identifier, unlocked_ids)
    if not title_id:
        return None
    key = _title_key(group_id, user_id)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mutator(data: dict) -> None:
        record = data.setdefault("users", {}).setdefault(key, {})
        record.update({"user_id": user_id, "group_id": group_id, "equipped": title_id, "updated_at": now_text})
        record["unlocked"] = _sort_title_ids(set(record.get("unlocked", [])) | {"default", title_id})

    mutate_json(TITLE_DATA_FILE, DEFAULT_TITLE_DATA, mutator)
    return TITLE_BY_ID[title_id]


def clear_equipped_title(user_id: str, group_id: str, points_info: dict | None = None) -> None:
    sync_user_titles(user_id, group_id, points_info)
    key = _title_key(group_id, user_id)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mutator(data: dict) -> None:
        record = data.setdefault("users", {}).setdefault(key, {})
        record.update({"user_id": user_id, "group_id": group_id, "equipped": "", "updated_at": now_text})
        record["unlocked"] = _sort_title_ids(set(record.get("unlocked", [])) | {"default"})

    mutate_json(TITLE_DATA_FILE, DEFAULT_TITLE_DATA, mutator)


def grant_title(user_id: str, group_id: str, title_id: str) -> TitleAchievement | None:
    achievement = TITLE_BY_ID.get(title_id)
    if not achievement:
        return None

    key = _title_key(group_id, user_id)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mutator(data: dict) -> None:
        record = data.setdefault("users", {}).setdefault(
            key,
            {
                "user_id": user_id,
                "group_id": group_id,
                "unlocked": ["default"],
                "equipped": "",
                "updated_at": now_text,
            },
        )
        unlocked = set(record.get("unlocked", [])) | {"default", title_id}
        record["user_id"] = user_id
        record["group_id"] = group_id
        record["unlocked"] = _sort_title_ids(unlocked)
        record["updated_at"] = now_text

    mutate_json(TITLE_DATA_FILE, DEFAULT_TITLE_DATA, mutator)
    return achievement


def render_title_list(user_id: str, group_id: str, points_info: dict | None = None) -> str:
    display = get_display_title(user_id, group_id, points_info)
    status = sync_user_titles(user_id, group_id, points_info)
    unlocked_ids = set(status["record"].get("unlocked", ["default"]))
    visible_title_ids = set(_visible_title_ids(unlocked_ids))
    metrics = status["metrics"]
    equipped_text = display["title"]

    lines = [
        "🎖 李太白给·成就称号 🎖",
        "=" * 22,
        f"当前称号：{equipped_text}",
        f"名号入册：{display['unlocked_count']}/{display['total_count']}",
        "用法：/佩戴称号 称号名 或 /佩戴称号 编号",
        "用法：/卸下称号",
        "=" * 22,
    ]

    current_category = ""
    unlocked_sorted = _sort_title_ids(unlocked_ids & visible_title_ids)
    unlocked_index = {title_id: index + 1 for index, title_id in enumerate(unlocked_sorted)}
    for achievement in ALL_TITLES:
        if achievement.id not in visible_title_ids:
            continue
        if achievement.category != current_category:
            current_category = achievement.category
            lines.append(f"【{current_category}】")

        unlocked = achievement.id in unlocked_ids
        prefix = "✓" if unlocked else "·"
        number = f"{unlocked_index[achievement.id]}." if unlocked else "  "
        if achievement.id == "default":
            progress = "已拥有"
        elif unlocked:
            progress = "已入册"
        else:
            current = metrics.get(achievement.metric, 0)
            progress = f"{min(current, achievement.threshold)}/{achievement.threshold}"
        lines.append(f"{prefix} {number} {achievement.title} - {achievement.description} · {progress}")

    lines.extend(["=" * 22, "『名号挂于衣襟上，行过群中自有风。』"])
    return "\n".join(lines)
