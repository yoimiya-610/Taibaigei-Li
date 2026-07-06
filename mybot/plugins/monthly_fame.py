from nonebot import get_bot, require
from nonebot.adapters.onebot.v11 import Bot

from mybot.common.config import get_daily_greet_groups
from mybot.common.logger import get_plugin_logger
from mybot.common.monthly_fame import settle_monthly_fame, previous_month
from mybot.common.user_utils import get_nickname


logger = get_plugin_logger(__name__)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


async def _render_monthly_fame_message(bot: Bot, group_id: int, result: dict) -> str:
    month = result.get("month") or previous_month()
    awards = result.get("awards", [])
    lines = [
        "🏮 李太白给·月度群风云榜 🏮",
        "━━━━━━━━━━━━━━━━━━",
        f"（抖开长卷）{month} 一月群风至此收束，今夜便在诸君名下排座分云。",
        "星灯列阵，墨榜高悬，且听本猫唱名。",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if not awards:
        lines.extend(
            [
                "本月风声尚轻，长卷暂未落下惊鸿姓名。",
                "━━━━━━━━━━━━━━━━━━",
                "『云旗未展天犹阔，铁马应知后会期。\n"
                "今夜暂教星斗静，来朝更起万重旗。\n"
                "江山不负藏锋客，风月终归拔剑时。\n"
                "待到群峰齐振处，满堂名姓动天池。』",
            ]
        )
        return "\n".join(lines)

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    rank_comments = {
        1: "点评：群星拱北，万象归旌，这一席当真压住满堂风月。",
        2: "点评：只差半步登峰，气势却已横开云路，来月大可再争魁首。",
        3: "点评：探花落座亦自生辉，一盏星灯已照出后来万里。",
    }
    for award in awards:
        rank = int(award.get("rank", 0))
        user_id = str(award.get("user_id") or "")
        nickname = await get_nickname(bot, user_id, context="群风云榜")
        gift_icon = award.get("gift_icon", "")
        gift_name = award.get("gift_name", "")
        reward_text = f"｜得 {gift_icon} {gift_name}" if gift_name else ""
        lines.append(f"{medals.get(rank, f'{rank}.')} {nickname} —— {award.get('title', '')}{reward_text}")
        comment = rank_comments.get(rank)
        if comment:
            lines.append(comment)

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "榜上名号已入册，前三锦礼也已收入背包；今夜掌声至此，来月再听龙吟。",
            "『金鼓裂空开夜色，旌旗卷月下高城。\n"
            "三台名姓悬天上，百席风声入酒觥。\n"
            "一卷评成惊海岳，满堂坐定动雷霆。\n"
            "莫言今夜云梯尽，明月还看后起旌。』",
        ]
    )
    return "\n".join(lines)


@scheduler.scheduled_job("cron", day=1, hour=9, minute=30, id="monthly_fame")
async def monthly_fame():
    try:
        bot: Bot = get_bot()
    except Exception as exc:
        logger.warning(f"月度风云榜获取 bot 失败: {exc}")
        return

    month = previous_month()
    for group_id in get_daily_greet_groups():
        try:
            result = settle_monthly_fame(str(group_id), month)
            if result.get("already"):
                continue
            message = await _render_monthly_fame_message(bot, group_id, result)
            await bot.send_group_msg(group_id=group_id, message=message)
        except Exception as exc:
            logger.exception(f"月度风云榜发送失败 group_id={group_id} month={month}: {exc}")
