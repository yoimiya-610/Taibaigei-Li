"""Help metadata and reusable copy renderers for Taibai Tavern."""

from mybot.common.ai_public_play_guides import PublicPlayGuideEntry
from mybot.common.help_registry import HelpItem

from .rules import (
    POINT_TO_WINE,
    RANDOM_MODE,
    SIGN_COUNT,
    calculate_reward_wine,
    current_multiplier_text,
    get_mode_multipliers,
)

HELP_ITEMS = (
    HelpItem("太白酒馆", "/太白酒馆 - 酒馆总览与酒钱规则", 10),
    HelpItem("太白酒馆", "/酒钱 - 查看酒馆酒钱", 20),
    HelpItem("太白酒馆", "/兑换酒钱 积分数 - 添酒钱", 30),
    HelpItem("太白酒馆", "/灵签翻盘 酒钱数 - 酒馆灵签局", 40),
    HelpItem("太白酒馆", "/墨宝寻踪 酒钱数 - 寻诗猜墨宝", 50),
    HelpItem("太白酒馆", "/对饮猜拳 @群友 酒钱数 - 原生猜拳对盏", 60),
)
COMMAND_ALIASES = (
    "太白酒馆",
    "酒钱",
    "我的酒钱",
    "酒钱余额",
    "兑换酒钱",
    "灵签翻盘",
    "翻签",
    "收签",
    "弃签",
    "墨宝寻踪",
    "寻踪",
    "观星",
    "对饮猜拳",
    "酒令猜拳",
    "猜拳对盏",
    "接盏",
    "应战猜拳",
    "拒盏",
)

PUBLIC_PLAY_GUIDES = (
    PublicPlayGuideEntry(
        key="taibai_tavern",
        keywords=("太白酒馆", "酒馆", "酒钱", "兑换酒钱", "灵签翻盘", "墨宝寻踪", "对饮猜拳", "酒令猜拳", "翻签", "收签", "弃签", "观星", "接盏"),
        intents=("怎么玩", "玩法", "规则", "命令", "怎么兑换", "比例", "费用", "步骤", "怎么查"),
        public_explanation=(
            f"太白酒馆使用酒钱，积分可按 1 积分换 {POINT_TO_WINE} 酒钱添入酒壶。"
            "/太白酒馆 可看总览，/酒钱 查余额，/兑换酒钱 积分数 添酒钱。"
            f"灵签翻盘用 /灵签翻盘 酒钱数 [凶签数] 开桌，共 {SIGN_COUNT} 签覆面，"
            "开桌后用 /翻签 位置 翻开，吉签可 /收签，/弃签 会退回一部分酒钱。"
            "墨宝寻踪用 /墨宝寻踪 酒钱数 开局，再用 /寻踪 意象 猜酒、月、剑、花、云、舟之一。"
            "对饮猜拳用 /对饮猜拳 @群友 酒钱数 邀战，对方 /接盏 后由本猫依次发送两枚 QQ 原生猜拳；"
            "胜者收下双方酒钱，平局各自原额归还。"
        ),
        related_commands=("/太白酒馆", "/酒钱", "/兑换酒钱 积分数", "/灵签翻盘 酒钱数 [凶签数]", "/翻签 位置", "/收签", "/弃签", "/墨宝寻踪 酒钱数", "/寻踪 意象", "/观星", "/对饮猜拳 @群友 酒钱数", "/接盏", "/拒盏"),
    ),
)


def _format_board(game: dict, reveal_all: bool = False) -> str:
    cells = []
    revealed = set(game.get("revealed", []))
    deck = game["deck"]
    for index, sign in enumerate(deck):
        if reveal_all or index in revealed:
            face = "吉" if sign == "吉" else "凶"
        else:
            face = "?"
        cells.append(f"{index + 1}.{face}")
    return "  ".join(cells)


def _format_ink_trace_options(game: dict) -> str:
    excluded = set(game.get("excluded", []))
    return "  ".join(f"{option}{'（空）' if option in excluded else ''}" for option in game["options"])


def _status_line(game: dict) -> str:
    good_count = int(game.get("good_count", 0))
    mode = game.get("mode", RANDOM_MODE)
    reward = calculate_reward_wine(game["stake_wine"], good_count, mode)
    return (
        f"已翻吉签：{good_count}/{SIGN_COUNT}\n"
        f"当前倍率：{current_multiplier_text(good_count, mode)}\n"
        f"当前可收：{reward} 酒钱"
    )



def _render_tavern_help() -> str:
    return (
        "🍶 太白酒馆 🍶\n"
        f"{'=' * 20}\n"
        "（本猫推开木门，酒旗在檐下慢慢晃）进了太白酒馆，先认这枚酒钱。\n"
        "积分可在柜上添作酒钱：1 积分，换 10 酒钱。\n"
        "酒钱入了壶，便在馆中流转；今日翻签，来日添新局，也都从这只酒壶里斟。\n"
        f"{'=' * 20}\n"
        "/酒钱 - 查看酒馆酒钱\n"
        "/兑换酒钱 积分数 - 添酒钱入壶\n"
        "/灵签翻盘 酒钱数 [凶签数] - 入灵签桌\n"
        "/墨宝寻踪 酒钱数 - 入旧卷寻墨宝\n"
        "/对饮猜拳 @群友 酒钱数 - 邀群友原生猜拳\n"
        f"{'=' * 20}\n"
        "灵签翻盘：五签覆面，自选其一翻开；吉签可收，凶签清桌。\n"
        "不写凶签数，便听酒馆随机排签；写 1-4，则凶签越多，彩头越高。\n"
        "墨宝寻踪：本猫把不同墨宝藏进酒、月、剑、花、云、舟之中；各有轻重，也各有彩头。\n"
        "对饮猜拳：对方接盏后，双方各封同额酒钱；本猫发两枚 QQ 原生猜拳，胜者收双份，平局各归原额。\n"
        f"{'=' * 20}\n"
        "『酒旗斜挂月初明，\n"
        "一分换得十钱声。\n"
        "莫问杯中归旧账，\n"
        "且留馆里续新程。』"
    )
