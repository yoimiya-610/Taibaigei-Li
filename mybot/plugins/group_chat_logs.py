from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="group_chat_logs",
    name="群聊记录",
    default_enabled=True,
    scope="group",
    permission_level=5,
    data_files=("data/group_chat_logs",),
    privacy_level="sensitive",
    backup_policy="optional",
)

from typing import Any

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.message import event_preprocessor

from mybot.common.feature_flags import is_feature_enabled
from mybot.common.group_chat_logs import (
    extract_sent_group_message,
    save_group_message_record,
    save_sent_group_message_record,
)
from mybot.common.logger import get_plugin_logger


COMMAND_ALIASES = (
    "群聊记录",
)

logger = get_plugin_logger(__name__)


@event_preprocessor
async def handle_group_chat_log(event: Event) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    try:
        if not is_feature_enabled("group_chat_logs", event.group_id):
            return
        # Bot output has one source of truth at the successful API boundary below.
        # Ignore any adapter loopback event regardless of API/event ordering.
        if str(event.user_id) == str(event.self_id):
            return
        save_group_message_record(event)
    except Exception as exc:
        logger.exception(
            "failed to save group chat log: group_id=%s user_id=%s error=%s",
            event.group_id,
            event.user_id,
            exc,
        )


@Bot.on_called_api
async def handle_sent_group_chat_log(
    bot: Bot,
    exception: Exception | None,
    api: str,
    data: dict[str, Any],
    _result: Any,
) -> None:
    if exception is not None:
        return
    sent_message = extract_sent_group_message(api, data)
    if sent_message is None:
        return
    group_id, message = sent_message
    try:
        if not is_feature_enabled("group_chat_logs", group_id):
            return
        save_sent_group_message_record(group_id, bot.self_id, message)
    except Exception as exc:
        logger.exception(
            "failed to save sent group chat log: group_id=%s self_id=%s api=%s error=%s",
            group_id,
            bot.self_id,
            api,
            exc,
        )
