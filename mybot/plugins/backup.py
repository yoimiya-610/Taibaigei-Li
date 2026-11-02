from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="backup",
    name="自动备份",
    default_enabled=True,
    scope="system",
    permission_level=None,
    privacy_level="sensitive",
    backup_policy="none",
)

from pathlib import Path

from mybot.common.backup import (
    BACKUP_DIR,
    BOT_ROOT,
    DEFAULT_BACKUP_SOURCES,
    create_verified_backup,
)
from mybot.common.config import (
    get_backup_hour,
    get_backup_minute,
    get_retention_settings,
)
from mybot.common.logger import get_plugin_logger
from mybot.common.retention import (
    RetentionSafetyError,
    apply_retention_after_verified_backup,
    format_size,
)


logger = get_plugin_logger(__name__)


def create_backup() -> Path:
    settings = get_retention_settings()
    result = create_verified_backup(
        backup_dir=BACKUP_DIR,
        sources=DEFAULT_BACKUP_SOURCES,
        include_group_chat_logs=settings.backup_include_group_chat_logs,
        include_image_library=settings.backup_include_image_library,
    )
    if (BOT_ROOT / ".env").exists():
        logger.info("备份已跳过 .env，避免密钥进入备份包")
    logger.info(
        "每日备份已生成并验证：文件数=%s，SHA-256 清单=%s",
        result.member_count,
        result.checksum_path.name,
    )

    if not settings.is_valid:
        for error in settings.errors:
            logger.warning("保留配置诊断：%s", error)
        logger.warning("保留配置无效，本次未清理任何群聊日志或旧备份")
        return result.path
    if not settings.cleanup_enabled:
        return result.path

    try:
        cleanup = apply_retention_after_verified_backup(settings, result)
    except RetentionSafetyError as exc:
        logger.warning("保留策略安全检查未通过，本次未继续清理：%s", exc)
        return result.path

    logger.info(
        "群聊日志保留清理完成：删除=%s，日期范围=%s，释放=%s",
        cleanup.group_logs.deleted_count,
        cleanup.group_logs.date_range or "无",
        format_size(cleanup.group_logs.released_bytes),
    )
    logger.info(
        "旧备份保留清理完成：删除=%s，日期范围=%s，释放=%s",
        cleanup.backups.deleted_count,
        cleanup.backups.date_range or "无",
        format_size(cleanup.backups.released_bytes),
    )
    return result.path


if __name__ != "__main__":
    from nonebot import require

    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    @scheduler.scheduled_job(
        "cron",
        hour=get_backup_hour(),
        minute=get_backup_minute(),
        id="daily_backup",
    )
    async def daily_backup():
        try:
            create_backup()
        except Exception as exc:
            logger.exception("每日备份未能完成：%s", exc)
else:
    print(create_backup())
