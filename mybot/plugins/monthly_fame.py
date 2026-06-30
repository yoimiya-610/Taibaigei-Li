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
        "=" * 22,
        f"（展卷观风）{month} 风云已定，本猫替诸位落榜为证。",
        "=" * 22,
    ]

    if not awards:
        lines.extend(
            [
                "本月风声尚轻，榜上暂未题名。",
                "=" * 22,
                "『江湖不怕一时静，来月风云再上楼。』",
            ]
        )
        return "\n".join(lines)

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for award in awards:
        rank = int(award.get("rank", 0))
        user_id = str(award.get("user_id") or "")
        nickname = await get_nickname(bot, user_id, context="群风云榜")
        lines.append(f"{medals.get(rank, f'{rank}.')} {nickname} —— {award.get('title', '')}")

    lines.extend(
        [
            "=" * 22,
            "榜上名号已入册，诸君自可择日佩之。",
            "『一月群风归此榜，几人名姓带星来。』",
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
