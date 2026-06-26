from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
from pathlib import Path

from zhdate import ZhDate


@dataclass(frozen=True)
class Festival:
    key: str
    name: str
    category: str
    priority: int = 100


FIXED_FESTIVALS = {
    (1, 1): Festival("new_year", "元旦", "公历节日", 30),
    (3, 8): Festival("womens_day", "妇女节", "纪念节日"),
    (3, 12): Festival("arbor_day", "植树节", "纪念节日"),
    (5, 1): Festival("labor_day", "劳动节", "公共节日", 40),
    (5, 4): Festival("youth_day", "青年节", "纪念节日"),
    (6, 1): Festival("childrens_day", "儿童节", "纪念节日"),
    (7, 1): Festival("party_day", "建党节", "纪念节日"),
    (8, 1): Festival("army_day", "建军节", "纪念节日"),
    (9, 10): Festival("teachers_day", "教师节", "纪念节日"),
    (9, 30): Festival("martyrs_day", "烈士纪念日", "纪念节日", 10),
    (10, 1): Festival("national_day", "国庆节", "公共节日", 20),
    (12, 13): Festival("memorial_day", "国家公祭日", "纪念节日", 10),
}

LUNAR_FESTIVALS = {
    (1, 1): Festival("spring_festival", "春节", "传统节日", 10),
    (1, 15): Festival("lantern_festival", "元宵节", "传统节日", 20),
    (2, 2): Festival("dragon_head", "龙抬头", "传统节日"),
    (5, 5): Festival("dragon_boat", "端午节", "传统节日", 20),
    (7, 7): Festival("qixi", "七夕节", "传统节日"),
    (7, 15): Festival("ghost_festival", "中元节", "传统节日"),
    (8, 15): Festival("mid_autumn", "中秋节", "传统节日", 20),
    (9, 9): Festival("double_ninth", "重阳节", "传统节日"),
    (12, 8): Festival("laba", "腊八节", "传统节日"),
}

SPECIAL_FESTIVALS = (
    Festival("new_year_eve", "除夕", "传统节日", 5),
    Festival("qingming", "清明节", "传统节日", 15),
    Festival("mothers_day", "母亲节", "常见节日"),
    Festival("fathers_day", "父亲节", "常见节日"),
)

SOLAR_TERMS = (
    ("solar_minor_cold", "小寒"),
    ("solar_major_cold", "大寒"),
    ("solar_start_spring", "立春"),
    ("solar_rain_water", "雨水"),
    ("solar_awakening_insects", "惊蛰"),
    ("solar_spring_equinox", "春分"),
    ("solar_qingming", "清明节气"),
    ("solar_grain_rain", "谷雨"),
    ("solar_start_summer", "立夏"),
    ("solar_grain_buds", "小满"),
    ("solar_grain_in_ear", "芒种"),
    ("solar_summer_solstice", "夏至"),
    ("solar_minor_heat", "小暑"),
    ("solar_major_heat", "大暑"),
    ("solar_start_autumn", "立秋"),
    ("solar_end_heat", "处暑"),
    ("solar_white_dew", "白露"),
    ("solar_autumn_equinox", "秋分"),
    ("solar_cold_dew", "寒露"),
    ("solar_frost_descent", "霜降"),
    ("solar_start_winter", "立冬"),
    ("solar_minor_snow", "小雪"),
    ("solar_major_snow", "大雪"),
    ("solar_winter_solstice", "冬至"),
)

# Dates are transcribed from the Hong Kong Observatory Gregorian-Lunar
# Calendar Conversion Tables. They are stored explicitly to avoid the
# one-day errors that approximate solar-term formulae can introduce.
SOLAR_TERM_DATES = {
    2026: (
        (1, 5), (1, 20), (2, 4), (2, 18), (3, 5), (3, 20),
        (4, 5), (4, 20), (5, 5), (5, 21), (6, 5), (6, 21),
        (7, 7), (7, 23), (8, 7), (8, 23), (9, 7), (9, 23),
        (10, 8), (10, 23), (11, 7), (11, 22), (12, 7), (12, 22),
    ),
    2027: (
        (1, 5), (1, 20), (2, 4), (2, 19), (3, 6), (3, 21),
        (4, 5), (4, 20), (5, 6), (5, 21), (6, 6), (6, 21),
        (7, 7), (7, 23), (8, 8), (8, 23), (9, 8), (9, 23),
        (10, 8), (10, 23), (11, 7), (11, 22), (12, 7), (12, 22),
    ),
    2028: (
        (1, 6), (1, 20), (2, 4), (2, 19), (3, 5), (3, 20),
        (4, 4), (4, 19), (5, 5), (5, 20), (6, 5), (6, 21),
        (7, 6), (7, 22), (8, 7), (8, 22), (9, 7), (9, 22),
        (10, 8), (10, 23), (11, 7), (11, 22), (12, 6), (12, 21),
    ),
    2029: (
        (1, 5), (1, 20), (2, 3), (2, 18), (3, 5), (3, 20),
        (4, 4), (4, 20), (5, 5), (5, 21), (6, 5), (6, 21),
        (7, 7), (7, 22), (8, 7), (8, 23), (9, 7), (9, 23),
        (10, 8), (10, 23), (11, 7), (11, 22), (12, 7), (12, 21),
    ),
}

SOLAR_TERM_SOURCE = "https://www.hko.gov.hk/en/gts/time/conversion.htm"


def _safe_date_after_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, month=2, day=28)


def three_year_window(start: date | None = None) -> tuple[date, date]:
    start = start or date.today()
    return start, _safe_date_after_years(start, 3) - timedelta(days=1)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (occurrence - 1) * 7)


def _qingming_date(year: int) -> date:
    if 2008 <= year <= 2039:
        # Leap years and the year immediately after them fall on April 4.
        return date(year, 4, 4 if year % 4 in {0, 1} else 5)
    if 2040 <= year <= 2071:
        return date(year, 4, 4 if year % 4 in {0, 1, 2} else 5)
    if 2072 <= year <= 2099:
        return date(year, 4, 4)
    raise ValueError(f"unsupported Qingming year: {year}")


def _append_if_in_range(
    rows: list[tuple[date, Festival]],
    festival_date: date,
    festival: Festival,
    start: date,
    end: date,
) -> None:
    if start <= festival_date <= end:
        rows.append((festival_date, festival))


def generate_festival_schedule(
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[date, Festival]]:
    if start is None:
        start = date.today()
    if end is None:
        _, end = three_year_window(start)
    if end < start:
        raise ValueError("end date must not be earlier than start date")

    rows: list[tuple[date, Festival]] = []
    special = {festival.key: festival for festival in SPECIAL_FESTIVALS}

    for year in range(start.year, end.year + 1):
        for (month, day), festival in FIXED_FESTIVALS.items():
            _append_if_in_range(rows, date(year, month, day), festival, start, end)

        solar_term_dates = SOLAR_TERM_DATES.get(year, ())
        if solar_term_dates and len(solar_term_dates) != len(SOLAR_TERMS):
            raise ValueError(f"incomplete solar term table for {year}")
        for (key, name), (month, day) in zip(SOLAR_TERMS, solar_term_dates):
            _append_if_in_range(
                rows,
                date(year, month, day),
                Festival(key, name, "二十四节气", 200),
                start,
                end,
            )

        _append_if_in_range(rows, _qingming_date(year), special["qingming"], start, end)
        _append_if_in_range(
            rows,
            _nth_weekday(year, 5, weekday=6, occurrence=2),
            special["mothers_day"],
            start,
            end,
        )
        _append_if_in_range(
            rows,
            _nth_weekday(year, 6, weekday=6, occurrence=3),
            special["fathers_day"],
            start,
            end,
        )

    for lunar_year in range(start.year - 1, end.year + 2):
        spring_festival = ZhDate(lunar_year, 1, 1).to_datetime().date()
        _append_if_in_range(
            rows,
            spring_festival - timedelta(days=1),
            special["new_year_eve"],
            start,
            end,
        )
        for (month, day), festival in LUNAR_FESTIVALS.items():
            festival_date = ZhDate(lunar_year, month, day).to_datetime().date()
            _append_if_in_range(rows, festival_date, festival, start, end)

    unique = {(day, festival.key): (day, festival) for day, festival in rows}
    return sorted(unique.values(), key=lambda row: (row[0], row[1].priority, row[1].name))


def get_festivals(day: date | None = None) -> tuple[Festival, ...]:
    day = day or date.today()
    return tuple(festival for _, festival in generate_festival_schedule(day, day))


def schedule_payload(start: date | None = None, end: date | None = None) -> dict:
    if start is None:
        start = date.today()
    if end is None:
        _, end = three_year_window(start)

    return {
        "generated_at": date.today().isoformat(),
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "note": "记录节日与二十四节气日期，不包含尚未公布或可能调整的放假、调休安排。",
        "solar_term_source": SOLAR_TERM_SOURCE,
        "festivals": [
            {"date": day.isoformat(), **asdict(festival)}
            for day, festival in generate_festival_schedule(start, end)
        ],
    }


def write_schedule(path: Path, start: date | None = None, end: date | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schedule_payload(start, end), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
