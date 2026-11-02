import re

from nonebot.adapters.onebot.v11 import Message, MessageEvent


# A copied QQ mention can arrive as plain text, including a full-width @.
# Only the bot's explicit name is a wake word; member targets still require IDs.
COPIED_BOT_MENTION = re.compile(r"[@＠]李太白给(?!\w)")


def is_chat_addressed(event: MessageEvent) -> bool:
    """Keep adapter addressing and recognize bot mentions anywhere in the message."""
    if event.is_tome():
        return True
    for segment in event.message:
        if segment.type == "at" and str(segment.data.get("qq", "")) == str(event.self_id):
            return True
        if segment.type == "text" and COPIED_BOT_MENTION.search(
            str(segment.data.get("text", ""))
        ):
            return True
    return False


def get_chat_text(event: MessageEvent) -> str:
    """Remove copied wake words without modifying the event or member mentions."""
    return "".join(
        COPIED_BOT_MENTION.sub("", str(segment.data.get("text", "")))
        for segment in event.message
        if segment.type == "text"
    ).strip()


def get_message_text(event: MessageEvent) -> str:
    """Return user-authored text while ignoring mentions and other segments."""
    return "".join(
        str(segment.data.get("text", ""))
        for segment in event.message
        if segment.type == "text"
    ).strip()


def get_first_at_user_id(message: Message | MessageEvent) -> str | None:
    """Return the first concrete QQ id from OneBot at segments."""
    segments = message.message if isinstance(message, MessageEvent) else message
    for segment in segments:
        if segment.type != "at":
            continue
        qq = segment.data.get("qq")
        if qq is None or str(qq) == "all":
            continue
        return str(qq)
    return None


def get_reply_message_id(message: Message | MessageEvent) -> str | None:
    """Return a concrete OneBot reply id without inferring it from text."""
    segment_sources = []
    if isinstance(message, MessageEvent):
        segment_sources.extend(
            source
            for source in (
                getattr(message, "message", None),
                getattr(message, "original_message", None),
            )
            if source is not None
        )
        reply = getattr(message, "reply", None)
        reply_id = getattr(reply, "message_id", None) if reply is not None else None
        if reply_id is not None and str(reply_id).strip():
            return str(reply_id).strip()
    else:
        segment_sources.append(message)

    for segments in segment_sources:
        for segment in segments:
            segment_type = getattr(segment, "type", None)
            data = getattr(segment, "data", None)
            if isinstance(segment, dict):
                segment_type = segment.get("type")
                data = segment.get("data")
            if segment_type != "reply" or not isinstance(data, dict):
                continue
            message_id = data.get("id")
            if message_id is not None and str(message_id).strip():
                return str(message_id).strip()
    return None


def is_explicit_command_text(text: str) -> bool:
    return text.lstrip().startswith(("/", "／"))
