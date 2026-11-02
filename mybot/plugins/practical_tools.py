from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="practical_tools",
    name="实用功能",
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
from mybot.common.practical_tools import (
    MAX_PRACTICAL_TEXT_LENGTH,
    MAX_CRYPTO_TEXT_LENGTH,
    PRACTICAL_TOOL_COST,
    TASKS,
    atbash_transform,
    bacon_decode,
    bacon_encode,
    base64_decode,
    base64_encode,
    build_task_prompt,
    binary_decode,
    binary_encode,
    caesar_transform,
    morse_decode,
    morse_encode,
    parse_caesar_request,
    parse_keyed_request,
    parse_mode_text,
    parse_morse_request,
    parse_polish_request,
    parse_rail_fence_request,
    rail_fence_decode,
    rail_fence_encode,
    unicode_escape_decode,
    unicode_escape_encode,
    url_decode,
    url_encode,
    vigenere_transform,
)
from mybot.common.usage_policy import (
    AI_REQUEST_QUOTA,
    OPERATION_COMPLETED,
    PaidOperationInsufficientBalance,
    PaidOperationService,
    PaidOperationSnapshot,
    QuotaPlan,
    UsageQuotaExceeded,
    paid_operation_processing_message,
    paid_operation_refund_message,
    quota_wait_message,
)


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("实用功能", f"/总结 内容 - 提炼要点，{PRACTICAL_TOOL_COST}积分", 20),
    HelpItem("实用功能", f"/润色 内容 - 改顺文案，{PRACTICAL_TOOL_COST}积分", 30),
    HelpItem("实用功能", f"/解释 内容 - 白话讲解，{PRACTICAL_TOOL_COST}积分", 40),
    HelpItem("实用功能", f"/凯撒 加密 3 内容 - 字母移位，{PRACTICAL_TOOL_COST}积分", 50),
    HelpItem("实用功能", f"/摩斯 编码 内容 - 摩斯互转，{PRACTICAL_TOOL_COST}积分", 60),
    HelpItem("实用功能", f"/Base64 编码 内容 - Base64互转，{PRACTICAL_TOOL_COST}积分", 70),
    HelpItem("实用功能", f"/URL编码 编码 内容 - URL互转，{PRACTICAL_TOOL_COST}积分", 80),
    HelpItem("实用功能", f"/栅栏 加密 3 内容 - 栅栏密码，{PRACTICAL_TOOL_COST}积分", 90),
)
COMMAND_ALIASES = (
    "总结", "摘要", "润色", "改写", "解释", "说明",
    "凯撒", "凯撒加密", "摩斯", "摩斯电码",
    "栅栏", "栅栏密码", "维吉尼亚", "维吉尼亚密码", "培根", "培根密码", "ROT13",
    "Base64", "URL编码", "Unicode", "反转", "替换", "二进制",
)


summary_cmd = on_command("总结", aliases={"摘要"}, priority=5, block=True)
polish_cmd = on_command("润色", aliases={"改写"}, priority=5, block=True)
explain_cmd = on_command("解释", aliases={"说明"}, priority=5, block=True)
caesar_cmd = on_command("凯撒", aliases={"凯撒加密"}, priority=5, block=True)
morse_cmd = on_command("摩斯", aliases={"摩斯电码"}, priority=5, block=True)
rail_fence_cmd = on_command("栅栏", aliases={"栅栏密码"}, priority=5, block=True)
vigenere_cmd = on_command("维吉尼亚", aliases={"维吉尼亚密码"}, priority=5, block=True)
bacon_cmd = on_command("培根", aliases={"培根密码"}, priority=5, block=True)
rot13_cmd = on_command("ROT13", aliases={"rot13"}, priority=5, block=True)
base64_cmd = on_command("Base64", aliases={"base64"}, priority=5, block=True)
url_cmd = on_command("URL编码", aliases={"url编码", "URL解码", "url解码"}, priority=5, block=True)
unicode_cmd = on_command("Unicode", aliases={"unicode", "Unicode编码", "Unicode解码"}, priority=5, block=True)
reverse_cmd = on_command("反转", aliases={"倒序"}, priority=5, block=True)
atbash_cmd = on_command("替换", aliases={"Atbash", "atbash", "埃特巴什"}, priority=5, block=True)
binary_cmd = on_command("二进制", aliases={"binary", "二进制编码", "二进制解码"}, priority=5, block=True)


CRYPTO_USAGES = {
    "凯撒密文": (
        "功能：把英文字母按指定数字位移；中文、数字和标点保持原样。",
        "用法：/凯撒 加密 3 hello 或 /凯撒 解密 3 khoor",
        "例：/凯撒 加密 3 Hello, World!",
    ),
    "摩斯电码": (
        "功能：英文、数字和常见标点与摩斯电码互相转换。",
        "用法：/摩斯 编码 SOS 或 /摩斯 解码 ... --- ...",
        "例：/摩斯 编码 SOS 2026",
    ),
    "栅栏密码": (
        "功能：按指定栏数把文字折返排列后重组。",
        "用法：/栅栏 加密 3 内容 或 /栅栏 解密 3 密文",
        "例：/栅栏 加密 3 WEAREDISCOVEREDFLEEATONCE",
    ),
    "维吉尼亚": (
        "功能：用英文密钥对英文字母做维吉尼亚加密或解密。",
        "用法：/维吉尼亚 加密 lemon attackatdawn 或 /维吉尼亚 解密 lemon lxfopvefrnhr",
        "例：/维吉尼亚 加密 key hello",
    ),
    "培根密码": (
        "功能：把英文字母转成 A/B 五位组合，也可反向解码。",
        "用法：/培根 编码 ABC 或 /培根 解码 AAAAA AAAAB AAABA",
        "例：/培根 编码 HELLO",
    ),
    "ROT13": (
        "功能：把英文字母固定移动 13 位；同一命令再转一次即可还原。",
        "用法：/ROT13 内容",
        "例：/ROT13 Hello",
    ),
    "Base64": (
        "功能：文本与 Base64 编码互相转换，常用于技术调试。",
        "用法：/Base64 编码 内容 或 /Base64 解码 5L2g5aW9",
        "例：/Base64 编码 你好",
    ),
    "URL编码": (
        "功能：文本与 URL 百分号编码互相转换。",
        "用法：/URL编码 编码 内容 或 /URL编码 解码 %E4%BD%A0%E5%A5%BD",
        "例：/URL编码 编码 你好 bot",
    ),
    "Unicode转义": (
        "功能：文本与 Unicode 转义写法互相转换。",
        "用法：/Unicode 编码 内容 或 /Unicode 解码 \\u4f60\\u597d",
        "例：/Unicode 编码 你好",
    ),
    "反转": (
        "功能：把整段文本倒序排列。",
        "用法：/反转 内容",
        "例：/反转 hello",
    ),
    "Atbash替换": (
        "功能：把英文字母按 A<->Z、B<->Y 镜像替换；再转一次即可还原。",
        "用法：/替换 内容",
        "例：/替换 Abc Z",
    ),
    "二进制": (
        "功能：文本与 UTF-8 字节二进制互相转换。",
        "用法：/二进制 编码 内容 或 /二进制 解码 01001000 01101001",
        "例：/二进制 编码 Hi",
    ),
}


def render_crypto_usage(title: str) -> str:
    lines = CRYPTO_USAGES.get(
        title,
        (
            "功能：进行一项本地文本转换。",
            "用法：请在命令后接内容。",
            "例：/反转 hello",
        ),
    )
    return (
        f"🧰 李太白给·{title} 🧰\n"
        "======================\n"
        f"{lines[0]}\n"
        f"{lines[1]}\n"
        f"{lines[2]}\n"
        f"每次消耗 {PRACTICAL_TOOL_COST} 积分。\n"
        "======================\n"
        "『密语须先递半句，本猫方可替君藏。』"
    )


def _event_group_id(event: MessageEvent) -> str | None:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return None


async def _charge_points_or_finish(
    matcher,
    event: MessageEvent,
    request_key: str,
    *,
    quota_plan: QuotaPlan | None = None,
) -> tuple[str, str, PaidOperationService, PaidOperationSnapshot]:
    group_id = _event_group_id(event)
    if not group_id:
        await matcher.finish(
            "（合上案头小卷）实用小令按群积分结算，请到群里再唤本猫。\n"
            "『独坐难翻群中卷，人声一落好成章。』"
        )

    user_id = event.get_user_id()
    operation_service = PaidOperationService()
    try:
        operation = operation_service.begin(
            feature_key="practical_tools",
            user_id=user_id,
            group_id=group_id,
            cost=PRACTICAL_TOOL_COST,
            request_key=request_key,
            quota_plan=quota_plan,
        )
    except UsageQuotaExceeded as exc:
        await matcher.finish(quota_wait_message(exc.decision))
    except PaidOperationInsufficientBalance as exc:
        await matcher.finish(
            f"（翻账本）这一回要 {PRACTICAL_TOOL_COST} 积分，阁下账上只有 {exc.balance} 积分。\n"
            "『先攒几枚杯中月，再请本猫磨短章。』"
        )
    except Exception as exc:
        logger.exception(f"实用小令开账失败 user_id={user_id} group_id={group_id}: {exc}")
        await matcher.finish(
            "（算盘一停）这笔墨资暂时落不了账，请稍后再试。\n"
            "『账页偶逢风作乱，待墨痕干再开章。』"
        )
    if operation.existing:
        await matcher.finish(paid_operation_processing_message())
    return user_id, group_id, operation_service, operation


async def _run_practical_task(matcher, event: MessageEvent, task_key: str, raw_text: str, *, style: str = "") -> None:
    task = TASKS[task_key]
    text = raw_text.strip()
    if not text:
        await matcher.finish(
            f"🧰 李太白给·{task.title} 🧰\n"
            "======================\n"
            f"{task.empty_hint}\n"
            f"每次消耗 {PRACTICAL_TOOL_COST} 积分。\n"
            "======================\n"
            "『空卷难磨成好句，递来一段便生光。』"
        )

    if len(text) > MAX_PRACTICAL_TEXT_LENGTH:
        await matcher.finish(
            f"（按住案卷）内容太长，本猫这一盏酒理不完。请压到 {MAX_PRACTICAL_TEXT_LENGTH} 字以内。\n"
            "『长卷须分三两次，短章方好见清光。』"
        )

    if not is_configured():
        await matcher.finish(
            "（摸了摸空墨囊）本猫今日尚未备好这支笔，积分先替你留着。\n"
            "『案前灯火未添满，且待明时再落章。』"
        )

    user_id, group_id, operation_service, operation = await _charge_points_or_finish(
        matcher,
        event,
        f"ai:{task_key}:{style}:{text}",
        quota_plan=AI_REQUEST_QUOTA,
    )
    prompt = build_task_prompt(task_key, text, style=style)
    try:
        reply = await prompt_completion(
            prompt,
            system=task.system_prompt,
            max_tokens=1200,
            temperature=0.3,
            timeout=60,
            raise_errors=True,
            usage_checked=True,
        )
        if not reply:
            raise RuntimeError(f"empty {task_key} reply")
    except Exception as exc:
        logger.exception(f"{task.command}失败 user_id={user_id} group_id={group_id}: {exc}")
        try:
            operation_service.refund(operation.operation_id, reason=f"{task_key}_failed")
        except Exception as refund_exc:
            logger.exception(f"实用小令退款待恢复 operation_id={operation.operation_id}: {refund_exc}")
            await matcher.finish("（收回案头笔）这一卷暂未写成，账页尚在核对，请勿重复递卷。")
        await matcher.finish(paid_operation_refund_message(PRACTICAL_TOOL_COST))

    try:
        operation_service.complete(operation.operation_id, result_key=reply)
    except Exception as exc:
        logger.exception(f"实用小令结账失败 operation_id={operation.operation_id}: {exc}")
        try:
            current = operation_service.get(operation.operation_id)
        except Exception as status_exc:
            logger.exception(f"实用小令状态核对失败 operation_id={operation.operation_id}: {status_exc}")
            await matcher.finish("（按住案卷）短章已成，墨账尚未干透，请勿重复递卷。")
        if current.status != OPERATION_COMPLETED:
            await matcher.finish("（按住案卷）短章已成，墨账尚未干透，请勿重复递卷。")

    await matcher.finish(
        f"🧰 李太白给·{task.title} 🧰\n"
        "======================\n"
        f"消耗：{PRACTICAL_TOOL_COST} 积分\n"
        "======================\n"
        f"{reply}"
    )


async def _run_local_crypto(matcher, event: MessageEvent, title: str, mode_label: str, input_text: str, result: str) -> None:
    if not input_text:
        await matcher.finish(render_crypto_usage(title))

    if len(input_text) > MAX_CRYPTO_TEXT_LENGTH:
        await matcher.finish(
            f"（按住密卷）内容太长，密文会绕晕酒壶。请压到 {MAX_CRYPTO_TEXT_LENGTH} 字以内。\n"
            "『密札宜短不宜繁，三行风月好收藏。』"
        )

    _user_id, _group_id, operation_service, operation = await _charge_points_or_finish(
        matcher,
        event,
        f"local:{title}:{mode_label}:{input_text}",
    )
    try:
        operation_service.complete(operation.operation_id, result_key=result)
    except Exception as exc:
        logger.exception(f"本地实用小令结账失败 operation_id={operation.operation_id}: {exc}")
        try:
            current = operation_service.get(operation.operation_id)
        except Exception as status_exc:
            logger.exception(f"本地实用小令状态核对失败 operation_id={operation.operation_id}: {status_exc}")
            await matcher.finish("（按住密卷）密文已成，墨账尚未干透，请勿重复递卷。")
        if current.status != OPERATION_COMPLETED:
            await matcher.finish("（按住密卷）密文已成，墨账尚未干透，请勿重复递卷。")
    await matcher.finish(
        f"🧰 李太白给·{title} 🧰\n"
        "======================\n"
        f"方式：{mode_label}\n"
        f"消耗：{PRACTICAL_TOOL_COST} 积分\n"
        "======================\n"
        f"{result}"
    )


@summary_cmd.handle()
async def handle_summary(event: MessageEvent, args: Message = CommandArg()):
    await _run_practical_task(summary_cmd, event, "summary", args.extract_plain_text())


@polish_cmd.handle()
async def handle_polish(event: MessageEvent, args: Message = CommandArg()):
    text, style = parse_polish_request(args.extract_plain_text())
    await _run_practical_task(polish_cmd, event, "polish", text, style=style)


@explain_cmd.handle()
async def handle_explain(event: MessageEvent, args: Message = CommandArg()):
    await _run_practical_task(explain_cmd, event, "explain", args.extract_plain_text())


@caesar_cmd.handle()
async def handle_caesar(event: MessageEvent, args: Message = CommandArg()):
    mode, shift, text = parse_caesar_request(args.extract_plain_text())
    result = caesar_transform(text, shift, decode=(mode == "decode")) if text else ""
    mode_label = f"{'解密' if mode == 'decode' else '加密'}｜位移 {shift}"
    await _run_local_crypto(caesar_cmd, event, "凯撒密文", mode_label, text, result)


@morse_cmd.handle()
async def handle_morse(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_morse_request(args.extract_plain_text())
    if mode == "decode":
        result, unknown = morse_decode(text)
        mode_label = "解码"
    else:
        result, unknown = morse_encode(text)
        mode_label = "编码"
    if unknown:
        note = "未识别：" + "、".join(unknown[:10])
        result = f"{result}\n\n{note}" if result else note
    await _run_local_crypto(morse_cmd, event, "摩斯电码", mode_label, text, result)


@rail_fence_cmd.handle()
async def handle_rail_fence(event: MessageEvent, args: Message = CommandArg()):
    mode, rails, text = parse_rail_fence_request(args.extract_plain_text())
    if rails < 2:
        await rail_fence_cmd.finish("（按住竹简）栅栏层数至少要 2 层，少了就只剩平地一张。")
    result = rail_fence_decode(text, rails) if mode == "decode" else rail_fence_encode(text, rails)
    mode_label = f"{'解密' if mode == 'decode' else '加密'}｜{rails} 栏"
    await _run_local_crypto(rail_fence_cmd, event, "栅栏密码", mode_label, text, result)


@vigenere_cmd.handle()
async def handle_vigenere(event: MessageEvent, args: Message = CommandArg()):
    mode, key, text = parse_keyed_request(args.extract_plain_text())
    if not key:
        await vigenere_cmd.finish(
            f"🧰 李太白给·维吉尼亚 🧰\n======================\n用法：/维吉尼亚 加密 lemon attackatdawn\n每次消耗 {PRACTICAL_TOOL_COST} 积分。\n======================\n『密钥不落纸上，长风难启暗门。』"
        )
    result, valid_key = vigenere_transform(text, key, decode=(mode == "decode"))
    if not valid_key:
        await vigenere_cmd.finish("（敲了敲密钥）密钥里至少要有一个英文字母。")
    mode_label = f"{'解密' if mode == 'decode' else '加密'}｜密钥 {key}"
    await _run_local_crypto(vigenere_cmd, event, "维吉尼亚", mode_label, text, result)


@bacon_cmd.handle()
async def handle_bacon(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_mode_text(args.extract_plain_text())
    if mode == "decode":
        result, unknown = bacon_decode(text)
        mode_label = "解码"
    else:
        result, unknown = bacon_encode(text)
        mode_label = "编码"
    if unknown:
        note = "未识别：" + "、".join(unknown[:10])
        result = f"{result}\n\n{note}" if result else note
    await _run_local_crypto(bacon_cmd, event, "培根密码", mode_label, text, result)


@rot13_cmd.handle()
async def handle_rot13(event: MessageEvent, args: Message = CommandArg()):
    _mode, text = parse_mode_text(args.extract_plain_text())
    await _run_local_crypto(rot13_cmd, event, "ROT13", "互转｜位移 13", text, caesar_transform(text, 13))


@base64_cmd.handle()
async def handle_base64(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_mode_text(args.extract_plain_text())
    result = base64_decode(text)[0] if mode == "decode" else base64_encode(text)
    mode_label = "解码" if mode == "decode" else "编码"
    await _run_local_crypto(base64_cmd, event, "Base64", mode_label, text, result)


@url_cmd.handle()
async def handle_url(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_mode_text(args.extract_plain_text())
    result = url_decode(text) if mode == "decode" else url_encode(text)
    mode_label = "解码" if mode == "decode" else "编码"
    await _run_local_crypto(url_cmd, event, "URL编码", mode_label, text, result)


@unicode_cmd.handle()
async def handle_unicode(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_mode_text(args.extract_plain_text())
    result = unicode_escape_decode(text)[0] if mode == "decode" else unicode_escape_encode(text)
    mode_label = "解码" if mode == "decode" else "编码"
    await _run_local_crypto(unicode_cmd, event, "Unicode转义", mode_label, text, result)


@reverse_cmd.handle()
async def handle_reverse(event: MessageEvent, args: Message = CommandArg()):
    text = args.extract_plain_text().strip()
    await _run_local_crypto(reverse_cmd, event, "反转", "倒序", text, text[::-1])


@atbash_cmd.handle()
async def handle_atbash(event: MessageEvent, args: Message = CommandArg()):
    _mode, text = parse_mode_text(args.extract_plain_text())
    await _run_local_crypto(atbash_cmd, event, "Atbash替换", "互转", text, atbash_transform(text))


@binary_cmd.handle()
async def handle_binary(event: MessageEvent, args: Message = CommandArg()):
    mode, text = parse_mode_text(args.extract_plain_text())
    if mode == "decode":
        result, invalid = binary_decode(text)
        if invalid:
            result = "未识别：" + "、".join(invalid[:10])
        mode_label = "解码"
    else:
        result = binary_encode(text)
        mode_label = "编码"
    await _run_local_crypto(binary_cmd, event, "二进制", mode_label, text, result)
