from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="premium_chat",
    name="Pro对话档位",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=("data/points.json", "data/paid_rounds.json"),
    privacy_level="personal",
    backup_policy="standard",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.ai_client import PRO_MODEL, chat_completion
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.persona import build_persona_prompt
from mybot.common.user_utils import get_nickname
from mybot.common.usage_policy import (
    AI_REQUEST_QUOTA,
    OPERATION_COMPLETED,
    PaidOperationInsufficientBalance,
    PaidOperationService,
    UsageQuotaExceeded,
    paid_operation_processing_message,
    paid_operation_refund_message,
    quota_wait_message,
)


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("AI对话", "/小酌档 - 简短 pro 形态对话，100积分", 20),
    HelpItem("AI对话", "/雅集档 - 深度 pro 形态对话，500积分", 30),
    HelpItem("AI对话", "/天命档 - 高性能 pro 形态对话，1000积分", 40),
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
        "system": build_persona_prompt(
            """你处于李太白给的 pro 形态。这是一次付费对话机会，不强制文艺腔，不强制结尾写诗。
优先直接回答用户的问题，允许严肃、实用、简洁；身份仍是耄耋，可保留少量李太白给的幽默气质。""",
            require_ending_poem=False,
            use_persona_voice=False,
        ),
    },
    500: {
        "name": "雅集档",
        "max_tokens": 1600,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "system": build_persona_prompt(
            """你处于李太白给的 pro 形态。这是一次中档付费对话机会，可以自由切换表达风格，但身份仍是耄耋。
优先解决用户真实需求：可以分析、规划、创作、解释、写代码思路或给出可执行建议。
需要时保持结构清晰；不强制作诗或玩梗。""",
            require_ending_poem=False,
            use_persona_voice=False,
        ),
    },
    1000: {
        "name": "天命拉满档",
        "max_tokens": 3200,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "system": build_persona_prompt(
            """你处于李太白给的 pro 形态。这是一次 1000 积分的拉满付费对话机会；身份仍是耄耋，但不受普通回复的结尾诗与文艺腔格式约束。
完全优先用户目标，可以严肃、深入、结构化、技术化，也可以按用户要求保持幽默或文艺。
回答要充分利用上下文，给出高质量、具体、可执行的结果；复杂问题要分层分析，避免空话。""",
            require_ending_poem=False,
            use_persona_voice=False,
        ),
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


async def call_premium_api(
    tier: dict, nickname: str, prompt: str, *, group_id: str | None = None
) -> str:
    system = tier["system"]
    messages = [
        {"role": "system", "content": system},
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
            usage_checked=True,
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
            usage_checked=True,
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

    operation_service = PaidOperationService()
    try:
        operation = operation_service.begin(
            feature_key="premium_chat",
            user_id=user_id,
            group_id=group_id,
            cost=cost,
            request_key=f"{cost}:{prompt}",
            quota_plan=AI_REQUEST_QUOTA,
        )
    except UsageQuotaExceeded as exc:
        await matcher.finish(quota_wait_message(exc.decision))
    except PaidOperationInsufficientBalance as exc:
        await matcher.finish(
            f"（翻账本）你当前只有 {exc.balance} 积分，"
            f"{tier['name']} 需要 {cost} 积分。"
        )
    except Exception as exc:
        logger.exception(f"付费对话开账失败 user_id={user_id} group_id={group_id}: {exc}")
        await matcher.finish("（算盘一停）这笔酒资暂未落稳，请稍后再试。")

    if operation.existing:
        await matcher.finish(paid_operation_processing_message())

    nickname = await get_nickname(bot, user_id, context=tier["name"])
    await matcher.send(
        f"（本猫扶正墨镜，酒资已封存）{tier['name']}已开，消耗 {cost} 积分。\n"
        f"正在切换{DISPLAY_FORM}，请稍候。"
    )

    try:
        reply = await call_premium_api(tier, nickname, prompt, group_id=group_id)
    except Exception as exc:
        logger.exception(f"{PRO_MODEL} 调用失败: {exc}")
        try:
            operation_service.refund(operation.operation_id, reason="premium_chat_failed")
        except Exception as refund_exc:
            logger.exception(f"付费对话退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await matcher.finish("（扶额）pro 形态变身失败，账页尚在核对，请勿重复开卷。")
        await matcher.finish(paid_operation_refund_message(cost))

    if not reply:
        try:
            operation_service.refund(operation.operation_id, reason="premium_chat_empty")
        except Exception as refund_exc:
            logger.exception(f"付费对话空结果退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await matcher.finish("（扶额）pro 形态没有吐出诗文，账页尚在核对，请勿重复开卷。")
        await matcher.finish(paid_operation_refund_message(cost))

    try:
        operation_service.complete(operation.operation_id, result_key=reply)
    except Exception as exc:
        logger.exception(f"付费对话结账失败 operation_id={operation.operation_id}: {exc}")
        try:
            current = operation_service.get(operation.operation_id)
        except Exception as status_exc:
            logger.exception(f"付费对话状态核对失败 operation_id={operation.operation_id}: {status_exc}")
            await matcher.finish("（按住账页）诗意已成，墨账尚未干透，请勿重复开卷。")
        if current.status != OPERATION_COMPLETED:
            await matcher.finish("（按住账页）诗意已成，墨账尚未干透，请勿重复开卷。")

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

