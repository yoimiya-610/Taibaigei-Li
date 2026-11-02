from __future__ import annotations

import ipaddress
import json
import math
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import sys
import tempfile
from typing import Callable, Iterable, Mapping, Optional, TextIO, Tuple

from dotenv import load_dotenv


MIN_PYTHON_VERSION = (3, 11)
PREFLIGHT_EXIT_CODE = 78
MAX_RETENTION_DAYS = 36500
MAX_BACKUP_KEEP_COUNT = 100000

BOT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_ROOT.parent
DEFAULT_ENV_FILE = BOT_ROOT / ".env"
DEFAULT_RUNTIME_DIRECTORIES = (
    ("DATA_DIR", BOT_ROOT / "data"),
    ("LOG_DIR", BOT_ROOT / "logs"),
    ("BACKUP_DIR", PROJECT_ROOT / "backups"),
)

_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_INTEGER_RE = re.compile(r"^[0-9]+$")
_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class CheckResult:
    code: str
    severity: Severity
    variable: str
    suggestion: str


@dataclass(frozen=True)
class PreflightReport:
    results: Tuple[CheckResult, ...]

    @property
    def has_errors(self) -> bool:
        return any(result.severity is Severity.ERROR for result in self.results)

    def by_severity(self, severity: Severity) -> Tuple[CheckResult, ...]:
        return tuple(result for result in self.results if result.severity is severity)


def load_startup_environment(env_file: Path = DEFAULT_ENV_FILE) -> bool:
    """Load the deployment .env without overriding systemd or shell variables."""
    return bool(load_dotenv(env_file, override=False))


def _value(environ: Mapping[str, str], name: str) -> Optional[str]:
    if name not in environ:
        return None
    return str(environ[name]).strip()


def _valid_host(value: str) -> bool:
    if not value or any(character.isspace() for character in value):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    if len(value) > 253 or any(character in value for character in "/\\[]:"):
        return False
    normalized = value[:-1] if value.endswith(".") else value
    return bool(normalized) and all(
        _HOST_LABEL_RE.fullmatch(label) for label in normalized.split(".")
    )


def _parse_command_start(value: str) -> Optional[bool]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return bool(parsed) and all(bool(item.strip()) for item in parsed)


def _valid_identifier_list(value: str) -> bool:
    items = [
        item.strip()
        for item in value.replace("，", ",").split(",")
        if item.strip()
    ]
    return bool(items) and all(item.isdigit() and int(item) > 0 for item in items)


def _parse_superusers(value: str) -> Optional[bool]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    if not all(
        not isinstance(item, bool)
        and str(item).strip().isdigit()
        and int(str(item).strip()) > 0
        for item in parsed
    ):
        return None
    return bool(parsed)


def _valid_bounded_int(value: str, minimum: int, maximum: int) -> bool:
    if not _INTEGER_RE.fullmatch(value):
        return False
    parsed = int(value)
    return minimum <= parsed <= maximum


def _valid_probability(value: str) -> bool:
    try:
        parsed = float(value)
    except ValueError:
        return False
    return math.isfinite(parsed) and 0.0 <= parsed <= 1.0


def _valid_bool(value: str) -> bool:
    return value.lower() in _TRUE_VALUES | _FALSE_VALUES


def _directory_is_writable(path: Path) -> bool:
    probe_path: Optional[Path] = None
    try:
        path.mkdir(parents=True, exist_ok=True)
        descriptor, probe_name = tempfile.mkstemp(prefix=".taibaigei-preflight-", dir=path)
        os.close(descriptor)
        probe_path = Path(probe_name)
        probe_path.unlink()
        return True
    except OSError:
        return False
    finally:
        if probe_path is not None and probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass


def check_startup_configuration(
    *,
    environ: Optional[Mapping[str, str]] = None,
    env_file: Path = DEFAULT_ENV_FILE,
    runtime_directories: Iterable[Tuple[str, Path]] = DEFAULT_RUNTIME_DIRECTORIES,
    python_version: Optional[Tuple[int, int, int]] = None,
    directory_probe: Optional[Callable[[Path], bool]] = None,
) -> PreflightReport:
    """Collect safe, structured diagnostics without exposing configuration values."""
    values = os.environ if environ is None else environ
    version = tuple(sys.version_info[:3]) if python_version is None else python_version
    probe = _directory_is_writable if directory_probe is None else directory_probe
    results = []

    def add(code: str, severity: Severity, variable: str, suggestion: str) -> None:
        results.append(CheckResult(code, severity, variable, suggestion))

    if version[:2] < MIN_PYTHON_VERSION:
        add(
            "python.unsupported",
            Severity.ERROR,
            "PYTHON_VERSION",
            "升级到 Python 3.11 或更高版本后重新启动。",
        )
    else:
        add(
            "python.supported",
            Severity.INFO,
            "PYTHON_VERSION",
            "无需修改；当前版本满足 Python 3.11 或更高版本要求。",
        )

    if env_file.is_file():
        add("env.present", Severity.INFO, "ENV_FILE", "无需修改；本地配置文件已找到。")
    else:
        add(
            "env.missing",
            Severity.WARNING,
            "ENV_FILE",
            "复制 mybot/.env.example 为 mybot/.env，或通过服务环境变量提供配置。",
        )

    host = _value(values, "HOST")
    if host is None:
        add(
            "host.default",
            Severity.INFO,
            "HOST",
            "如需覆盖默认监听地址，请在 mybot/.env 中设置合法主机名或 IP 地址。",
        )
    elif not _valid_host(host):
        add(
            "host.invalid",
            Severity.ERROR,
            "HOST",
            "设置为合法主机名或 IP 地址，不要包含协议、路径或空白字符。",
        )
    else:
        add("host.valid", Severity.INFO, "HOST", "无需修改；监听地址格式有效。")

    port = _value(values, "PORT")
    if port is None:
        add(
            "port.default",
            Severity.INFO,
            "PORT",
            "如需与 OneBot 接入地址保持一致，请显式设置 1 至 65535 的端口。",
        )
    elif not _valid_bounded_int(port, 1, 65535):
        add(
            "port.invalid",
            Severity.ERROR,
            "PORT",
            "设置为 1 至 65535 的十进制整数。",
        )
    else:
        add("port.valid", Severity.INFO, "PORT", "无需修改；监听端口格式有效。")

    command_start = _value(values, "COMMAND_START")
    if command_start is None:
        add(
            "command_start.default",
            Severity.INFO,
            "COMMAND_START",
            '如需覆盖默认命令前缀，请使用 JSON 字符串数组，例如 ["/"]。',
        )
    else:
        parsed_command_start = _parse_command_start(command_start)
        if parsed_command_start is None:
            add(
                "command_start.invalid",
                Severity.ERROR,
                "COMMAND_START",
                '设置为 JSON 字符串数组，例如 ["/"]。',
            )
        elif not parsed_command_start:
            add(
                "command_start.empty",
                Severity.WARNING,
                "COMMAND_START",
                "至少设置一个非空命令前缀；修复前服务仍启动，但命令匹配可能偏离预期。",
            )
        else:
            add(
                "command_start.valid",
                Severity.INFO,
                "COMMAND_START",
                "无需修改；命令前缀格式有效。",
            )

    bot_admins = _value(values, "BOT_ADMINS")
    superusers = _value(values, "SUPERUSERS")
    has_valid_admin = False
    if bot_admins:
        if _valid_identifier_list(bot_admins):
            has_valid_admin = True
            add("bot_admins.valid", Severity.INFO, "BOT_ADMINS", "无需修改；管理员格式有效。")
        else:
            add(
                "bot_admins.invalid",
                Severity.WARNING,
                "BOT_ADMINS",
                "改为以逗号分隔的正整数 ID；修复前系统级管理命令可能不可用。",
            )
    if superusers is not None:
        parsed_superusers = _parse_superusers(superusers)
        if parsed_superusers is None:
            add(
                "superusers.invalid",
                Severity.ERROR,
                "SUPERUSERS",
                "设置为由正整数 ID 组成的 JSON 数组。",
            )
        else:
            has_valid_admin = has_valid_admin or parsed_superusers
            add("superusers.valid", Severity.INFO, "SUPERUSERS", "无需修改；管理员格式有效。")
    if not has_valid_admin and not bot_admins:
        add(
            "admins.missing",
            Severity.WARNING,
            "BOT_ADMINS/SUPERUSERS",
            "至少配置一种管理员变量；未配置时系统级管理命令保持不可用。",
        )

    api_key = _value(values, "DEEPSEEK_API_KEY")
    if api_key:
        add(
            "ai.configured",
            Severity.INFO,
            "DEEPSEEK_API_KEY",
            "无需修改；相关 AI 能力可在运行时使用。",
        )
    else:
        add(
            "ai.disabled",
            Severity.WARNING,
            "DEEPSEEK_API_KEY",
            "需要 AI 能力时再配置；留空只关闭相关能力，纯本地功能可继续启动。",
        )

    access_token = _value(values, "ONEBOT_ACCESS_TOKEN")
    if access_token:
        add(
            "onebot_token.configured",
            Severity.INFO,
            "ONEBOT_ACCESS_TOKEN",
            "无需修改；请确认 OneBot 协议端使用同一秘密配置。",
        )
    else:
        add(
            "onebot_token.optional",
            Severity.INFO,
            "ONEBOT_ACCESS_TOKEN",
            "跨主机或非可信网络部署时建议配置，并在 OneBot 协议端保持一致。",
        )

    identifier_lists = (
        ("DAILY_GREET_GROUPS", "定时问候将保持关闭，或忽略无法识别的条目。"),
    )
    for name, fallback in identifier_lists:
        raw = _value(values, name)
        if raw is None or not raw:
            add(f"{name.lower()}.default", Severity.INFO, name, f"无需修改；{fallback}")
        elif _valid_identifier_list(raw):
            add(f"{name.lower()}.valid", Severity.INFO, name, "无需修改；列表格式有效。")
        else:
            add(
                f"{name.lower()}.invalid",
                Severity.WARNING,
                name,
                "改为以逗号分隔的正整数 ID；修复前相关自动化能力保持关闭。",
            )

    probability = _value(values, "RANDOM_REPLY_CHANCE")
    if probability is None or not probability:
        add(
            "random_reply_chance.default",
            Severity.INFO,
            "RANDOM_REPLY_CHANCE",
            "无需修改；未设置时使用既有默认概率。",
        )
    elif _valid_probability(probability):
        add(
            "random_reply_chance.valid",
            Severity.INFO,
            "RANDOM_REPLY_CHANCE",
            "无需修改；概率格式有效。",
        )
    else:
        add(
            "random_reply_chance.invalid",
            Severity.WARNING,
            "RANDOM_REPLY_CHANCE",
            "设置为 0 至 1 之间的有限数字；修复前使用既有安全默认值。",
        )

    bounded_settings = (
        ("BACKUP_HOUR", 0, 23, "小时"),
        ("BACKUP_MINUTE", 0, 59, "分钟"),
    )
    for name, minimum, maximum, label in bounded_settings:
        raw = _value(values, name)
        if raw is None or not raw:
            add(
                f"{name.lower()}.default",
                Severity.INFO,
                name,
                f"无需修改；未设置时使用既有默认{label}。",
            )
        elif _valid_bounded_int(raw, minimum, maximum):
            add(f"{name.lower()}.valid", Severity.INFO, name, f"无需修改；{label}格式有效。")
        else:
            add(
                f"{name.lower()}.invalid",
                Severity.WARNING,
                name,
                f"设置为 {minimum} 至 {maximum} 的整数；修复前使用既有安全默认值。",
            )

    retention_settings = (
        ("GROUP_CHAT_LOG_RETENTION_DAYS", 0, MAX_RETENTION_DAYS, "保留天数"),
        ("BACKUP_KEEP_DAYS", 0, MAX_RETENTION_DAYS, "保留天数"),
        ("BACKUP_KEEP_COUNT", 0, MAX_BACKUP_KEEP_COUNT, "保留数量"),
    )
    for name, minimum, maximum, label in retention_settings:
        raw = _value(values, name)
        if raw is None:
            continue
        if not raw:
            add(
                f"{name.lower()}.default",
                Severity.INFO,
                name,
                f"无需修改；空值使用既有默认{label}。",
            )
        elif _valid_bounded_int(raw, minimum, maximum):
            add(f"{name.lower()}.valid", Severity.INFO, name, f"无需修改；{label}格式有效。")
        else:
            add(
                f"{name.lower()}.invalid",
                Severity.WARNING,
                name,
                f"设置为 {minimum} 至 {maximum} 的整数；修复前使用既有安全默认值。",
            )

    retention_booleans = (
        "BACKUP_INCLUDE_GROUP_CHAT_LOGS",
        "BACKUP_INCLUDE_IMAGE_LIBRARY",
    )
    for name in retention_booleans:
        raw = _value(values, name)
        if raw is None:
            continue
        if not raw:
            add(
                f"{name.lower()}.default",
                Severity.INFO,
                name,
                "无需修改；空值使用既有安全默认值。",
            )
        elif _valid_bool(raw):
            add(f"{name.lower()}.valid", Severity.INFO, name, "无需修改；布尔值格式有效。")
        else:
            add(
                f"{name.lower()}.invalid",
                Severity.WARNING,
                name,
                "设置为 true 或 false；修复前使用既有安全默认值。",
            )

    for variable, path in runtime_directories:
        if probe(path):
            add(
                f"directory.{variable.lower()}.writable",
                Severity.INFO,
                variable,
                "无需修改；运行目录可写。",
            )
        else:
            add(
                f"directory.{variable.lower()}.unwritable",
                Severity.ERROR,
                variable,
                "为机器人运行账号授予对应项目相对目录的创建与写入权限。",
            )

    return PreflightReport(tuple(results))


def emit_startup_report(report: PreflightReport, stream: Optional[TextIO] = None) -> None:
    output = sys.stderr if stream is None else stream
    for result in report.results:
        print(
            f"[startup][{result.severity.value}] {result.variable}：{result.suggestion}",
            file=output,
        )
    if report.has_errors:
        print(
            f"[startup][error] STARTUP：修复以上 error 后重试；服务尚未绑定端口，退出码为 {PREFLIGHT_EXIT_CODE}。",
            file=output,
        )
    else:
        print(
            "[startup][info] STARTUP：配置检查完成；warning 不阻止服务继续启动。",
            file=output,
        )
