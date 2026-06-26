from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule

from common.feature_flags import is_feature_enabled
from common.message_utils import get_message_text, is_explicit_command_text

# 违禁词列表
BLACKLIST_WORDS = ["方思琰", "fsy","fangsiyan"]
COMMAND_ALIASES = tuple(BLACKLIST_WORDS)

def check_blacklist(event: MessageEvent) -> bool:
    """只检查普通文本中的违禁词，不让命令参数或 @ 昵称触发。"""
    if not is_feature_enabled("blacklist"):
        return False

    msg = get_message_text(event)
    if not msg or is_explicit_command_text(msg):
        return False

    msg = msg.lower()
    for word in BLACKLIST_WORDS:
        if word.lower() in msg:
            return True
    return False

# 只有包含违禁词才会触发这个 matcher，block=True 阻止后续所有处理
blacklist_check = on_message(rule=Rule(check_blacklist), priority=1, block=True)

@blacklist_check.handle()
async def handle_blacklist(event: MessageEvent):
    await blacklist_check.finish("关注悠依米亚喵，关注悠依米亚谢谢喵")
