import importlib
import pkgutil

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter


def _load_package_plugins(package_name: str, eager_modules: tuple[str, ...] = ()) -> None:
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


nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotAdapter)
_load_package_plugins("mybot.plugins", eager_modules=("points",))
_load_package_plugins("mybot.plugins_disabled")


def main() -> None:
    """Start the OneBot service for the installed console entry point."""
    nonebot.run()


if __name__ == "__main__":
    main()
