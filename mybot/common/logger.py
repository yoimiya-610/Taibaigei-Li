import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # Windows does not allow renaming a log file held by another process.
            if self.stream is None:
                self.stream = self._open()

            current_time = int(time.time())
            rollover_at = self.computeRollover(current_time)
            while rollover_at <= current_time:
                rollover_at += self.interval
            self.rolloverAt = rollover_at


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        file_handler = SafeTimedRotatingFileHandler(
            LOG_DIR / "bot.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
            delay=True,
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger


def get_plugin_logger(module_name: str) -> logging.Logger:
    plugin_name = module_name.removeprefix("plugins.").removeprefix("common.")
    return get_logger(f"plugin.{plugin_name}")


bot_logger = get_logger("bot")


def log_info(msg: str):
    bot_logger.info(msg)


def log_error(msg: str):
    bot_logger.error(msg)


def log_exception(msg: str):
    bot_logger.exception(msg)


def log_warning(msg: str):
    bot_logger.warning(msg)


def log_game(game: str, user: str, action: str, result: str = ""):
    """记录游戏日志"""
    bot_logger.info(f"[GAME:{game}] {user} - {action} {result}")


def log_points(user: str, change: int, reason: str):
    """记录积分变动"""
    bot_logger.info(f"[POINTS] {user} {'+' if change >= 0 else ''}{change} ({reason})")
