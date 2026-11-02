from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="data_diagnostics",
    name="数据透明与诊断",
    default_enabled=True,
    scope="system",
    permission_level=None,
    data_files=("data/admin_audit.json",),
    privacy_level="sensitive",
    backup_policy="standard",
    protected=True,
)

import asyncio

from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg

from mybot.common.admin import is_admin_user
from mybot.common.config import get_image_library_settings, get_retention_settings
from mybot.common.data_health import (
    DataFileKind,
    DiagnosticSeverity,
    SystemDiagnosticReport,
    build_system_diagnostic,
    iter_data_file_manifest,
)
from mybot.common.feature_flags import is_feature_enabled
from mybot.common.help_registry import HelpItem
from mybot.common.onebot_capabilities import (
    CAPABILITY_LABELS,
    Capability,
    CapabilityStatus,
    ConnectionStatus,
    OneBotCapabilitySnapshot,
    get_onebot_capability_snapshot,
)
from mybot.common.retention import format_size


HELP_ITEMS = (
    HelpItem("系统说明", "/本群数据 - 查看本群收录功能与保留策略", 35),
    HelpItem("系统说明", "/系统诊断 - 查看存储、任务、插件与备份状态", 36, system_admin_only=True),
)
COMMAND_ALIASES = ("本群数据", "系统诊断")
PUBLIC_COMMANDS = ("本群数据",)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


_CONNECTION_LABELS = {
    ConnectionStatus.DISCONNECTED: "未连接",
    ConnectionStatus.PROBING: "已连接，探测中",
    ConnectionStatus.CONNECTED: "已连接",
    ConnectionStatus.DEGRADED: "已连接，探测降级",
}
_CAPABILITY_STATUS_LABELS = {
    CapabilityStatus.SUPPORTED: "可用",
    CapabilityStatus.UNSUPPORTED: "不支持",
    CapabilityStatus.UNKNOWN: "未知",
    CapabilityStatus.DEGRADED: "降级",
}
_PROBE_ISSUE_LABELS = {
    "timeout": "只读探测超时",
    "api_error": "只读探测未获回应",
    "invalid_response": "只读探测回应无法识别",
    "internal_error": "能力登记暂时降级",
    "reported_unhealthy": "协议端报告状态异常",
    "disconnected": "适配器连接已断开",
}


def _feature_line(group_id: str, feature_key: str, label: str, description: str, retention: str) -> str:
    enabled = is_feature_enabled(feature_key, group_id)
    status = "开" if enabled else "关"
    action = description if enabled else "已停止新增；既有记录仍保留"
    return f"{status}｜{label}：{action}；{retention}"


def render_group_data_summary(group_id: str | int) -> str:
    group_key = str(group_id)
    retention = get_retention_settings()
    image_settings = get_image_library_settings()
    log_retention = (
        "不自动到期"
        if retention.group_chat_log_retention_days <= 0
        else f"保留 {retention.group_chat_log_retention_days} 天"
    )
    log_backup = "进入每日备份" if retention.backup_include_group_chat_logs else "不进入每日备份"
    image_backup = "进入每日备份" if retention.backup_include_image_library else "不进入每日备份"
    image_limit = (
        f"无自动到期，限 {image_settings.max_group_images} 张/"
        f"{format_size(image_settings.max_group_bytes)}，{image_backup}"
    )

    lines = [
        "📚 李太白给·本群数据 📚",
        "=" * 22,
        "（摊开明白账）这里只说明收什么、留多久，不展示任何群友明细。",
        "=" * 22,
        _feature_line(group_key, "fortune", "签到与运势", "记录签到、补签与运势档案", "无自动到期，进入标准备份"),
        _feature_line(group_key, "points", "积分与称号", "记录群内积分、账务与称号", "无自动到期，进入标准备份"),
        _feature_line(group_key, "gift", "魅力与礼物", "记录魅力、赠礼与背包", "无自动到期，进入标准备份"),
        _feature_line(group_key, "monthly_fame", "月度风云", "按群统计月榜与奖励", "无自动到期，进入标准备份"),
        _feature_line(group_key, "poetry_society", "群诗社", "记录投稿、选票、结卷与往卷", "无自动到期，进入标准备份"),
        _feature_line(group_key, "group_admin_assistant", "群管理助手", "记录消息索引、精华、名片授权与活动", "活动归档每群保留最近 30 份，进入标准备份"),
        _feature_line(group_key, "group_chat_logs", "群聊记录", "持续收录精简群消息记录", f"{log_retention}，{log_backup}"),
        _feature_line(group_key, "image_library", "群聊图片库", "只在群友明确使用 /收图 时收藏", image_limit),
        "=" * 22,
        "关闭功能只停止新增，不会自动清除旧记录；删除或导出请联系系统管理员。",
    ]
    if retention.errors:
        lines.append("当前保留配置有误，自动清理已按安全规则停用。")
    lines.extend(
        [
            "『明账摊开知去处，",
            "旧痕封卷不轻删。",
            "若问风月留多久，",
            "且看今朝这一栏。』",
        ]
    )
    return "\n".join(lines)


def _count_issues(report: SystemDiagnosticReport, severity: DiagnosticSeverity) -> int:
    return sum(1 for item in report.issues if item.severity is severity)


def _render_onebot_summary(snapshot: OneBotCapabilitySnapshot) -> list[str]:
    implementation = snapshot.implementation_name or "未识别"
    if snapshot.implementation_version:
        implementation = f"{implementation} {snapshot.implementation_version}"
    probe_note = _PROBE_ISSUE_LABELS.get(snapshot.probe_issue or "", "无")
    lines = [
        f"OneBot：{_CONNECTION_LABELS[snapshot.connection_status]}；"
        f"适配器 {snapshot.adapter_name}；实现 {implementation}；探测备注 {probe_note}",
    ]
    for capability in Capability:
        record = snapshot.capability(capability)
        lines.append(
            f"能力｜{CAPABILITY_LABELS[capability]}："
            f"{_CAPABILITY_STATUS_LABELS[record.status]}（{record.status.value}）"
        )
    return lines


def render_system_diagnostic(
    report: SystemDiagnosticReport,
    onebot_snapshot: OneBotCapabilitySnapshot | None = None,
) -> str:
    storage = report.storage
    tasks = report.tasks
    plugins = report.plugins
    backups = report.backups
    audit = report.audit
    healthy_jobs = tasks.expected_jobs - len(tasks.missing_jobs)
    latest_backup = backups.latest_at.strftime("%Y-%m-%d %H:%M:%S") if backups.latest_at else "尚无"
    checksum_text = {
        "valid": "校验通过",
        "present": "清单存在（启动未深验）",
        "missing": "缺校验清单",
        "invalid": "校验失败",
        "none": "无",
    }.get(backups.latest_checksum, backups.latest_checksum)
    archive_text = {
        "valid": "可安全打开",
        "invalid": "无法安全打开",
        "unchecked": "未深验",
    }.get(backups.latest_archive, backups.latest_archive)
    errors = _count_issues(report, DiagnosticSeverity.ERROR)
    warnings = _count_issues(report, DiagnosticSeverity.WARNING)
    capability_lines = _render_onebot_summary(
        onebot_snapshot or get_onebot_capability_snapshot()
    )

    lines = [
        "🩺 李太白给·系统诊断 🩺",
        "=" * 22,
        f"检查时间：{report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "本次巡检只读，不创建、不修复、不覆盖运行数据。",
        *capability_lines,
        "=" * 22,
        f"存储：清单 v{storage.manifest_version}，{storage.manifest_entries} 项；"
        f"已存在 {storage.existing_entries}，尚未生成 {storage.missing_entries}；"
        f"检查 {storage.checked_files} 个文件/{format_size(storage.checked_bytes)}",
        f"任务：计划任务 {healthy_jobs}/{tasks.expected_jobs}；"
        f"付费恢复钩子 {'在册' if tasks.recovery_hooks_installed else '缺失'}；"
        f"未完成付费回合 {tasks.unfinished_paid_rounds}（已到期 {tasks.due_paid_rounds}）",
        f"队列：名片 {tasks.queued_card_jobs}（异常 {tasks.abnormal_card_jobs}）；活动计时 {tasks.active_activity_timers}（异常 {tasks.abnormal_activity_timers}）",
        f"插件：已加载 {plugins.loaded_plugins}/{plugins.declared_plugins}；数据路径 {plugins.manifest_paths} 项",
        f"备份：{backups.backup_count} 份；最新 {latest_backup}；{checksum_text}；{archive_text}",
        f"审计：保留 {audit.retained_records} 条，轮替 {audit.dropped_records} 条；最近 {audit.latest_at or '尚无'}",
        "=" * 22,
        f"结论：错误 {errors}，提醒 {warnings}",
    ]
    if report.issues:
        ordered = sorted(
            report.issues,
            key=lambda item: (item.severity is not DiagnosticSeverity.ERROR, item.component, item.code),
        )
        for item in ordered[:8]:
            mark = "错" if item.severity is DiagnosticSeverity.ERROR else "醒"
            path = f"｜{item.path}" if item.path else ""
            lines.append(f"{mark} {item.message}{path}")
        if len(ordered) > 8:
            lines.append(f"……另有 {len(ordered) - 8} 条，请查启动日志。")
    else:
        lines.append("（收起听诊筒）诸卷平安，任务、插件与备份均未见异样。")
    if storage.unknown_paths:
        lines.append("未登记路径：" + "、".join(storage.unknown_paths[:5]))
    if storage.scan_truncated:
        lines.append("目录文件较多，本轮内容抽检已达上限；目录体积仍已统计。")
    lines.append("用 /系统诊断 清单 可查看全部数据路径与 schema 版本。")
    return "\n".join(lines)


def render_data_manifest() -> str:
    kind_names = {
        DataFileKind.JSON: "JSON",
        DataFileKind.YAML_TREE: "YAML目录",
        DataFileKind.IMAGE_LIBRARY: "图片目录",
    }
    specs = iter_data_file_manifest()
    lines = [
        "📑 李太白给·数据文件清单 📑",
        "=" * 22,
        f"共 {len(specs)} 项；下列 vN 为当前代码支持的 schema 版本。",
    ]
    for spec in specs:
        lines.append(f"v{spec.schema_version}｜{kind_names[spec.kind]}｜{spec.path}")
    lines.append("缺失文件表示功能尚未产生数据，不会由巡检自动创建。")
    return "\n".join(lines)


group_data = on_command("本群数据", priority=3, block=True)
system_diagnostic = on_command("系统诊断", priority=3, block=True)


@group_data.handle()
async def handle_group_data(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await group_data.finish("（合上群卷）/本群数据 只在对应群中展示，请回群里唤本猫。")
    await group_data.finish(render_group_data_summary(event.group_id))


@system_diagnostic.handle()
async def handle_system_diagnostic(event: MessageEvent, args: Message = CommandArg()):
    if not is_admin_user(event.get_user_id()):
        await system_diagnostic.finish("（合上总册）此卷只交系统掌柜过目。")
    action = args.extract_plain_text().strip()
    if action:
        if action != "清单":
            await system_diagnostic.finish("（拨正听诊筒）用法：/系统诊断 [清单]")
        await system_diagnostic.finish(render_data_manifest())
    report = await asyncio.to_thread(
        build_system_diagnostic,
        scheduler,
        deep_backup_verify=True,
    )
    await system_diagnostic.finish(render_system_diagnostic(report))
