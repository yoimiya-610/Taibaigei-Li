from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotAdapter)
project_root = Path(__file__).resolve().parent
nonebot.load_plugins(str(project_root / "plugins"))
nonebot.load_plugins(str(project_root / "plugins_disabled"))

if __name__ == "__main__":
    nonebot.run()
