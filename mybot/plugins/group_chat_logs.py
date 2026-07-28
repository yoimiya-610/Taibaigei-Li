from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule

from mybot.common.feature_flags import is_feature_enabled
from mybot.common.group_chat_logs import save_group_message_record
from mybot.common.logger import get_plugin_logger


COMMAND_ALIASES = (
    "群聊记录",
)

logger = get_plugin_logger(__name__)


def _is_group_message(event) -> bool:
    return isinstance(event, GroupMessageEvent)


group_chat_log_collector = on_message(rule=Rule(_is_group_message), priority=99, block=False)


@group_chat_log_collector.handle()
async def handle_group_chat_log(event: GroupMessageEvent):
    if not is_feature_enabled("group_chat_logs", event.group_id):
        return

    try:
        save_group_message_record(event)
    except Exception as exc:
        logger.exception(
            "failed to save group chat log: group_id=%s user_id=%s error=%s",
            event.group_id,
            event.user_id,
            exc,
        )
