from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

from mybot.common.admin import is_admin_user
from mybot.common.help_registry import HelpItem
from mybot.common.onebot_capabilities import (
    CAPABILITY_LABELS,
    Capability,
    CapabilityStatus,
    ConnectionStatus,
    OneBotCapabilitySnapshot,
    get_onebot_capability_snapshot,
)


HELP_ITEMS = (
    HelpItem(
        "系统说明",
        "/系统诊断 - 查看 OneBot 连接与能力摘要",
        30,
        system_admin_only=True,
    ),
)
COMMAND_ALIASES = ("系统诊断",)
PUBLIC_COMMANDS: tuple[str, ...] = ()

_CONNECTION_LABELS = {
    ConnectionStatus.DISCONNECTED: "未连接",
    ConnectionStatus.PROBING: "已连接，探测中",
    ConnectionStatus.CONNECTED: "已连接",
    ConnectionStatus.DEGRADED: "已连接，探测降级",
}
_STATUS_LABELS = {
    CapabilityStatus.SUPPORTED: "可用",
    CapabilityStatus.UNSUPPORTED: "不支持",
    CapabilityStatus.UNKNOWN: "未知",
    CapabilityStatus.DEGRADED: "降级",
}
_ISSUE_LABELS = {
    "timeout": "只读探测超时",
    "api_error": "只读探测未获回应",
    "invalid_response": "只读探测回应无法识别",
    "internal_error": "能力登记暂时降级",
    "reported_unhealthy": "协议端报告状态异常",
    "disconnected": "适配器连接已断开",
}


def render_system_diagnostic(
    snapshot: OneBotCapabilitySnapshot | None = None,
) -> str:
    current = snapshot or get_onebot_capability_snapshot()
    implementation = current.implementation_name or "未识别"
    if current.implementation_version:
        implementation = f"{implementation} {current.implementation_version}"
    probe_note = _ISSUE_LABELS.get(current.probe_issue or "", "无")

    lines = [
        "🩺 李太白给·系统诊断 🩺",
        "=" * 22,
        "（扶正墨镜）本猫只翻连接与能力账，不抄密钥和门牌。",
        f"OneBot 连接：{_CONNECTION_LABELS[current.connection_status]}",
        f"适配器：{current.adapter_name}",
        f"实现：{implementation}",
        f"探测备注：{probe_note}",
        "=" * 22,
        "能力摘要：",
    ]
    for capability in Capability:
        record = current.capability(capability)
        lines.append(
            f"- {CAPABILITY_LABELS[capability]}：{_STATUS_LABELS[record.status]}"
            f"（{record.status.value}）"
        )
    lines.extend(
        [
            "=" * 22,
            "unknown 表示尚无无副作用依据；真实业务调用会只回填对应能力。",
            "『门前风信分明记，一处灯昏不碍城。』",
        ]
    )
    return "\n".join(lines)


system_diagnostic = on_command("系统诊断", priority=3, block=True)


@system_diagnostic.handle()
async def handle_system_diagnostic(event: MessageEvent):
    if not is_admin_user(event.get_user_id()):
        await system_diagnostic.finish("（合上诊脉簿）此页只交系统掌柜过目。")
    await system_diagnostic.finish(render_system_diagnostic())
