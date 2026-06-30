import tarfile
from datetime import datetime
from pathlib import Path

from mybot.common.config import get_backup_hour, get_backup_minute
from mybot.common.logger import get_plugin_logger


BOT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_ROOT.parent
BACKUP_DIR = PROJECT_ROOT / "backups"
BACKUP_LOG = BACKUP_DIR / "backup.log"
logger = get_plugin_logger(__name__)

DEFAULT_BACKUP_SOURCES = (
    (BOT_ROOT / "data", "data"),
    (BOT_ROOT / "plugins", "plugins"),
    (BOT_ROOT / ".env.example", ".env.example"),
)

SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def should_skip(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    return path.suffix in SKIP_SUFFIXES


def add_path_to_tar(archive: tarfile.TarFile, source: Path, arcname: str) -> int:
    if not source.exists():
        return 0

    if source.is_file():
        if should_skip(source):
            return 0
        archive.add(source, arcname=arcname)
        return 1

    archive.add(source, arcname=arcname, recursive=False)
    count = 1

    for path in source.rglob("*"):
        if should_skip(path):
            continue

        relative_path = path.relative_to(source)
        archive_name = (Path(arcname) / relative_path).as_posix()
        archive.add(path, arcname=archive_name, recursive=False)
        count += 1

    return count


def get_backup_sources() -> tuple[tuple[Path, str], ...]:
    return DEFAULT_BACKUP_SOURCES


def append_backup_log(timestamp: str, message: str) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with BACKUP_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"bot_backup_{timestamp}.tar.gz"

    try:
        with tarfile.open(backup_file, "w:gz") as archive:
            added_count = 0
            for source, arcname in get_backup_sources():
                added_count += add_path_to_tar(archive, source, arcname)

        if (BOT_ROOT / ".env").exists():
            logger.info("备份已跳过 .env，避免密钥进入备份包")

        append_backup_log(timestamp, f"备份完成: {backup_file}, 文件数: {added_count}")
        return backup_file
    except Exception as exc:
        append_backup_log(timestamp, f"备份失败: {exc}")
        raise


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
            backup_file = create_backup()
            logger.info(f"每日备份完成: {backup_file}")
        except Exception as exc:
            logger.exception(f"每日备份失败: {exc}")
else:
    print(create_backup())

