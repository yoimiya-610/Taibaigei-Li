import time

from nonebot.adapters.onebot.v11 import Bot

from mybot.common.logger import get_plugin_logger


logger = get_plugin_logger(__name__)

NICKNAME_CACHE_TTL = 600
_nickname_cache: dict[str, tuple[str, float]] = {}


async def get_nickname(bot: Bot, user_id: str | int, *, context: str = "") -> str:
    normalized_id = str(user_id)
    now = time.time()
    cached = _nickname_cache.get(normalized_id)
    if cached and now - cached[1] < NICKNAME_CACHE_TTL:
        return cached[0]

    try:
        user_info = await bot.get_stranger_info(user_id=int(normalized_id))
        nickname = str(user_info.get("nickname") or normalized_id)
        _nickname_cache[normalized_id] = (nickname, now)
        return nickname
    except Exception as exc:
        context_text = f" context={context}" if context else ""
        logger.warning(f"获取用户昵称失败 user_id={normalized_id}{context_text}: {exc}")
        return normalized_id
