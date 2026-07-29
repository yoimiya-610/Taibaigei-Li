import importlib
import pkgutil

from mybot.common.startup_preflight import (
    PREFLIGHT_EXIT_CODE,
    check_startup_configuration,
    emit_startup_report,
    load_startup_environment,
)


_initialized = False


def _load_package_plugins(package_name: str, eager_modules: tuple[str, ...] = ()) -> None:
    import nonebot

    package = importlib.import_module(package_name)
    available_modules = {
        module_info.name.rsplit(".", 1)[-1]: module_info.name
        for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
    }
    for module_name in eager_modules:
        if module_path := available_modules.pop(module_name, None):
            nonebot.load_plugin(module_path)
    for module_name in sorted(available_modules):
        if not module_name.startswith("_"):
            nonebot.load_plugin(available_modules[module_name])


def initialize_bot():
    """Initialize NoneBot and load business plugins after preflight succeeds."""
    global _initialized
    import nonebot
    from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
    from mybot.common.onebot_capabilities import register_onebot_capability_hooks

    if _initialized:
        return nonebot

    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotAdapter)
    register_onebot_capability_hooks(driver)
    _load_package_plugins("mybot.plugins", eager_modules=("points",))
    _load_package_plugins("mybot.plugins_disabled")
    _initialized = True
    return nonebot


def bootstrap():
    """Load local configuration, emit diagnostics, then initialize the bot."""
    load_startup_environment()
    report = check_startup_configuration()
    emit_startup_report(report)
    if report.has_errors:
        raise SystemExit(PREFLIGHT_EXIT_CODE)
    return initialize_bot()


_nonebot_runtime = bootstrap()


def main() -> None:
    """Start the OneBot service for the installed console entry point."""
    _nonebot_runtime.run()


if __name__ == "__main__":
    main()
