from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="translate",
    name="翻译",
    default_enabled=True,
    scope="group",
    permission_level=2,
    data_files=("data/points.json", "data/paid_rounds.json"),
    privacy_level="personal",
    backup_policy="standard",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.ai_client import is_configured, prompt_completion
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.persona import build_persona_prompt
from mybot.common.translation import (
    MAX_TRANSLATION_TEXT_LENGTH,
    TRANSLATION_COST,
    TranslationRequest,
    parse_translation_request,
    supported_language_help,
)
from mybot.common.usage_policy import (
    AI_REQUEST_QUOTA,
    OPERATION_COMPLETED,
    PaidOperationInsufficientBalance,
    PaidOperationService,
    PaidOperationSnapshot,
    UsageQuotaExceeded,
    paid_operation_processing_message,
    paid_operation_refund_message,
    quota_wait_message,
)


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("实用功能", f"/翻译 内容 - 中英互译，{TRANSLATION_COST}积分", 10),
)
COMMAND_ALIASES = ("翻译", "translate", "fy")


TRANSLATION_SYSTEM_PROMPT = build_persona_prompt(
    """你处于李太白给的翻译工作模式。精准翻译用户文本，不闲聊，不解释流程，不添加诗句。
保持原意、语气、格式和换行；必要时让译文自然适合目标语言。
遇到专业名词、产品名、技术术语、人名、地名、机构名、作品名等专有表达时，首次出现用“译名（原文）”格式保留原文。
除译文外不要输出标题、注释、免责声明或额外说明。""",
    require_ending_poem=False,
    use_persona_voice=False,
)


translate_cmd = on_command("翻译", aliases={"translate", "fy"}, priority=5, block=True)


def build_translation_prompt(request: TranslationRequest) -> str:
    return f"""请将下列文本从{request.source_language}翻译为{request.target_language}。

要求：
1. 只输出译文。
2. 保持原文信息完整，不增删事实。
3. 专业名词、技术术语、专有名词首次出现时按“译名（原文）”保留原文。
4. 若原文中已有括号原文，不要重复堆叠。

原文：
{request.text}"""


def _event_group_id(event: MessageEvent) -> str | None:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


async def _charge_points_or_finish(
    event: MessageEvent,
    request_key: str,
) -> tuple[str, str, PaidOperationService, PaidOperationSnapshot]:
    group_id = _event_group_id(event)
    if not group_id:
        await translate_cmd.finish(
            "（合上小词典）翻译按群积分结算，请到群里再递来原文。\n"
            "『独坐无账难沽酒，群中一语好通桥。』"
        )

    user_id = event.get_user_id()
    operation_service = PaidOperationService()
    try:
        operation = operation_service.begin(
            feature_key="translate",
            user_id=user_id,
            group_id=group_id,
            cost=TRANSLATION_COST,
            request_key=request_key,
            quota_plan=AI_REQUEST_QUOTA,
        )
    except UsageQuotaExceeded as exc:
        await translate_cmd.finish(quota_wait_message(exc.decision))
    except PaidOperationInsufficientBalance as exc:
        await translate_cmd.finish(
            f"（翻账本）这一回译文要 {TRANSLATION_COST} 积分，阁下账上只有 {exc.balance} 积分。\n"
            "『先攒半囊明月色，再请本猫渡词关。』"
        )
    except Exception as exc:
        logger.exception(f"翻译开账失败 user_id={user_id} group_id={group_id}: {exc}")
        await translate_cmd.finish(
            "（算盘一停）这笔译资暂时落不了账，请稍后再试。\n"
            "『账页偶逢风作乱，待墨痕干再通言。』"
        )
    if operation.existing:
        await translate_cmd.finish(paid_operation_processing_message())
    return user_id, group_id, operation_service, operation


@translate_cmd.handle()
async def handle_translate(event: MessageEvent, args: Message = CommandArg()):
    raw_text = args.extract_plain_text()
    request = parse_translation_request(raw_text)
    if request is None:
        await translate_cmd.finish(supported_language_help())

    if len(request.text) > MAX_TRANSLATION_TEXT_LENGTH:
        await translate_cmd.finish(
            f"（按住词卷）原文太长，本猫一口酒渡不过去。请压到 {MAX_TRANSLATION_TEXT_LENGTH} 字以内。\n"
            "『千言须分三两盏，慢把长风译成桥。』"
        )

    if not is_configured():
        await translate_cmd.finish(
            "（摸了摸空词囊）本猫今日尚未备好译笔，积分先替你留着。\n"
            "『词桥未点灯前火，且待明时再渡舟。』"
        )

    user_id, group_id, operation_service, operation = await _charge_points_or_finish(
        event,
        f"{request.source_language}:{request.target_language}:{request.text}",
    )
    prompt = build_translation_prompt(request)
    try:
        reply = await prompt_completion(
            prompt,
            system=TRANSLATION_SYSTEM_PROMPT,
            max_tokens=1200,
            temperature=0.2,
            timeout=60,
            raise_errors=True,
            usage_checked=True,
        )
        if not reply:
            raise RuntimeError("empty translation reply")
    except Exception as exc:
        logger.exception(f"翻译失败 user_id={user_id} group_id={group_id}: {exc}")
        try:
            operation_service.refund(operation.operation_id, reason="translation_failed")
        except Exception as refund_exc:
            logger.exception(f"翻译退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await translate_cmd.finish("（收回译笔）这句暂未译成，账页尚在核对，请勿重复递卷。")
        await translate_cmd.finish(paid_operation_refund_message(TRANSLATION_COST))

    try:
        operation_service.complete(operation.operation_id, result_key=reply)
    except Exception as exc:
        logger.exception(f"翻译结账失败 operation_id={operation.operation_id}: {exc}")
        try:
            current = operation_service.get(operation.operation_id)
        except Exception as status_exc:
            logger.exception(f"翻译状态核对失败 operation_id={operation.operation_id}: {status_exc}")
            await translate_cmd.finish("（按住词卷）译文已成，墨账尚未干透，请勿重复递卷。")
        if current.status != OPERATION_COMPLETED:
            await translate_cmd.finish("（按住词卷）译文已成，墨账尚未干透，请勿重复递卷。")

    await translate_cmd.finish(
        "🌐 李太白给·翻译 🌐\n"
        "======================\n"
        f"方向：{request.source_language} → {request.target_language}\n"
        f"消耗：{TRANSLATION_COST} 积分\n"
        "======================\n"
        f"{reply}"
    )
