import sys
from types import ModuleType


def _module_aliases(module: ModuleType) -> set[str]:
    raw_aliases = getattr(module, "COMMAND_ALIASES", ())
    aliases = set()
    for alias in raw_aliases:
        if isinstance(alias, str):
            normalized = alias.strip()
            if normalized:
                aliases.add(normalized)
    return aliases


def collect_command_aliases() -> set[str]:
    aliases = set()
    for module_name, module in list(sys.modules.items()):
        if module_name.removeprefix("mybot.").startswith("plugins."):
            aliases.update(_module_aliases(module))
    return aliases


def is_known_command(message: str) -> bool:
    text = message.strip()
    if not text:
        return True
    if text.startswith(("/", "／")):
        return True

    for alias in collect_command_aliases():
        if text == alias:
            return True
        if text.startswith(alias):
            rest = text[len(alias):]
            if rest and rest[0].isspace():
                return True
    return False
