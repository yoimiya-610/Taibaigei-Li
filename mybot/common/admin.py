from nonebot import get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from mybot.common.config import get_env_int_list


def get_admin_user_ids() -> set[str]:
    admin_ids = {str(user_id) for user_id in get_env_int_list("BOT_ADMINS")}

    try:
        superusers = getattr(get_driver().config, "superusers", set())
    except ValueError:
        superusers = set()

    for user_id in superusers:
        admin_ids.add(str(user_id))

    return admin_ids


def is_admin_user(user_id: str | int) -> bool:
    return str(user_id) in get_admin_user_ids()


def is_group_admin(event: MessageEvent) -> bool:
    if is_admin_user(event.get_user_id()):
        return True
    if not isinstance(event, GroupMessageEvent):
        return False
    return getattr(event.sender, "role", "member") in {"owner", "admin"}
