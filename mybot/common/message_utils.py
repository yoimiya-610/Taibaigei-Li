from nonebot.adapters.onebot.v11 import Message, MessageEvent


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


def is_explicit_command_text(text: str) -> bool:
    return text.lstrip().startswith(("/", "／"))
