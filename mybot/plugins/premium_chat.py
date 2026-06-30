from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.ai_client import PRO_MODEL, chat_completion
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.plugins.points import get_points, refund_points, spend_points
from mybot.common.user_utils import get_nickname


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("AI对话", "/小酌档 - 简短Pro对话，100积分", 20),
    HelpItem("AI对话", "/雅集档 - 深度Pro对话，500积分", 30),
    HelpItem("AI对话", "/天命档 - 高性能Pro对话，1000积分", 40),
)
COMMAND_ALIASES = ("小酌档", "雅集档", "天命档")


DISPLAY_FORM = "pro 形态"

TIERS = {
    100: {
        "name": "小酌档",
        "max_tokens": 800,
        "temperature": 0.7,
        "top_p": 0.85,
        "thinking": {"type": "disabled"},
        "system": """你是李太白给，也可以称自己为本猫。
这是一次付费对话机会。你不需要被普通李太白给插件的固定格式束缚：不强制每句文艺腔，不强制结尾写诗。
优先直接回答用户的问题，允许严肃、实用、简洁；可以保留少量李太白给的幽默气质。""",
    },
    500: {
        "name": "雅集档",
        "max_tokens": 1600,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "system": """你是李太白给的增强对话形态。
这是一次中档付费对话机会。你可以自由切换风格，不局限于原本的猫猫诗人结构。
优先解决用户真实需求：可以分析、规划、创作、解释、写代码思路或给出可执行建议。
需要时保持结构清晰；不需要强行作诗或玩梗。""",
    },
    1000: {
        "name": "天命拉满档",
        "max_tokens": 3200,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "system": """你是李太白给的最高性能形态。
这是一次 1000 积分的拉满付费对话机会。完全优先用户目标，不受普通李太白给固定人设、结尾诗、文艺腔限制。
你可以严肃、深入、结构化、技术化，也可以根据用户要求保持幽默或文艺。
回答要充分利用上下文，给出高质量、具体、可执行的结果；复杂问题要分层分析，避免空话。""",
    },
}

USAGE = """💬 李太白给·付费对话 💬
====================
用法：
/小酌档 问题  - 100积分
/雅集档 问题  - 500积分
/天命档 问题  - 1000积分

例：
/小酌档 帮我想一句群公告
/雅集档 分析一下我这段计划
/天命档 写一个完整执行方案

天命档性能拉满，限制最少。"""


light_chat = on_command("小酌档", priority=5, block=True)
gathering_chat = on_command("雅集档", priority=5, block=True)
destiny_chat = on_command("天命档", priority=5, block=True)


async def call_premium_api(tier: dict, nickname: str, prompt: str) -> str:
    messages = [
        {"role": "system", "content": tier["system"]},
        {"role": "user", "content": f"用户昵称：{nickname}\n\n用户问题：\n{prompt}"},
    ]

    if tier["thinking"]["type"] == "enabled":
        reply = await chat_completion(
            messages,
            model=PRO_MODEL,
            max_tokens=tier["max_tokens"],
            thinking=tier["thinking"],
            reasoning_effort=tier["reasoning_effort"],
            timeout=90,
            raise_errors=True,
        )
    else:
        reply = await chat_completion(
            messages,
            model=PRO_MODEL,
            max_tokens=tier["max_tokens"],
            temperature=tier["temperature"],
            top_p=tier["top_p"],
            thinking=tier["thinking"],
            timeout=90,
            raise_errors=True,
        )

    if reply is None:
        raise RuntimeError("empty_ai_reply")
    return reply


async def finish_long_reply(matcher, reply: str):
    max_len = 1800
    chunks = [reply[i : i + max_len] for i in range(0, len(reply), max_len)]
    if not chunks:
        await matcher.finish("（扶额）pro 形态没有吐出半句诗文，本次积分已退回。")

    for chunk in chunks[:-1]:
        await matcher.send(chunk)
    await matcher.finish(chunks[-1])


async def handle_paid_chat(matcher, cost: int, bot: Bot, event: MessageEvent, args: Message):
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("（摇头）付费对话目前按群积分结算，请在群里使用。")

    prompt = args.extract_plain_text().strip()
    if not prompt:
        await matcher.finish(USAGE)

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    tier = TIERS[cost]

    points = get_points(user_id, group_id)
    if points["current"] < cost:
        await matcher.finish(
            f"（翻账本）你当前只有 {points['current']} 积分，"
            f"{tier['name']} 需要 {cost} 积分。"
        )

    if not spend_points(user_id, group_id, cost):
        await matcher.finish("（扶额）扣除积分失败，请稍后再试。")

    nickname = await get_nickname(bot, user_id, context=tier["name"])
    await matcher.send(
        f"💬 已开启 {tier['name']}，扣除 {cost} 积分。\n"
        f"（本猫正在切换{DISPLAY_FORM}，请稍候）"
    )

    try:
        reply = await call_premium_api(tier, nickname, prompt)
    except Exception as exc:
        logger.exception(f"{PRO_MODEL} 调用失败: {exc}")
        refund_points(user_id, group_id, cost)
        await matcher.finish(
            f"（扶额）pro形态变身失败，本次 {cost} 积分已退回。"
        )

    if not reply:
        refund_points(user_id, group_id, cost)
        await matcher.finish(
            f"（扶额）pro 形态没有吐出半句诗文，本次 {cost} 积分已退回。"
        )

    header = (
        f"💬 李太白给·{tier['name']} 💬\n"
        f"====================\n"
        f"形态：{DISPLAY_FORM}\n"
        f"消耗：{cost} 积分\n"
        f"====================\n"
    )
    await finish_long_reply(matcher, header + reply)


@light_chat.handle()
async def handle_light_chat(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    await handle_paid_chat(light_chat, 100, bot, event, args)


@gathering_chat.handle()
async def handle_gathering_chat(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    await handle_paid_chat(gathering_chat, 500, bot, event, args)


@destiny_chat.handle()
async def handle_destiny_chat(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    await handle_paid_chat(destiny_chat, 1000, bot, event, args)

