from nonebot.adapters.onebot.v11 import MessageEvent


def get_message_text(event: MessageEvent) -> str:
    """Return user-authored text while ignoring mentions and other segments."""
    return "".join(
        str(segment.data.get("text", ""))
        for segment in event.message
        if segment.type == "text"
    ).strip()


def is_explicit_command_text(text: str) -> bool:
    return text.lstrip().startswith(("/", "／"))
