from __future__ import annotations

from typing import Any

from nonebot.adapters.onebot.v11 import Bot

from mybot.common.onebot_capabilities import Capability, call_capability_api


MANAGER_ROLES = {"owner", "admin"}


class PlatformOperationError(RuntimeError):
    """A safe, user-facing category for a failed OneBot operation."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


async def _call(
    bot: Bot,
    action: str,
    *,
    capability: Capability | None = None,
    **params,
) -> Any:
    try:
        if capability is not None:
            return await call_capability_api(
                bot,
                capability,
                action,
                **params,
            )
        return await bot.call_api(action, **params)
    except Exception as exc:
        raise PlatformOperationError("unavailable") from exc


async def get_member(bot: Bot, group_id: str, user_id: str) -> dict:
    result = await _call(
        bot,
        "get_group_member_info",
        group_id=group_id,
        user_id=user_id,
        no_cache=True,
    )
    if not isinstance(result, dict):
        raise PlatformOperationError("invalid_response")
    return result


async def is_qq_manager(bot: Bot, group_id: str, user_id: str) -> bool:
    member = await get_member(bot, group_id, user_id)
    return str(member.get("role", "")).lower() in MANAGER_ROLES


async def require_platform_managers(
    bot: Bot,
    group_id: str,
    operator_id: str,
) -> None:
    if not await is_qq_manager(bot, group_id, operator_id):
        raise PlatformOperationError("operator_not_manager")
    if not await is_qq_manager(bot, group_id, str(bot.self_id)):
        raise PlatformOperationError("bot_not_manager")


async def require_bot_manager(bot: Bot, group_id: str) -> None:
    if not await is_qq_manager(bot, group_id, str(bot.self_id)):
        raise PlatformOperationError("bot_not_manager")


def _numeric_id(value: str | int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlatformOperationError("invalid_response") from exc


async def set_essence(bot: Bot, message_id: str) -> None:
    await _call(
        bot,
        "set_essence_msg",
        capability=Capability.ESSENCE_MESSAGE,
        message_id=message_id,
    )


async def delete_essence(bot: Bot, message_id: str) -> None:
    await _call(
        bot,
        "delete_essence_msg",
        capability=Capability.ESSENCE_MESSAGE,
        message_id=message_id,
    )


async def get_essence_list(bot: Bot, group_id: str) -> list[dict]:
    result = await _call(
        bot,
        "get_essence_msg_list",
        capability=Capability.ESSENCE_MESSAGE,
        group_id=group_id,
    )
    return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []


async def set_group_card(bot: Bot, group_id: str, user_id: str, card: str) -> None:
    await _call(
        bot,
        "set_group_card",
        group_id=_numeric_id(group_id),
        user_id=_numeric_id(user_id),
        card=card,
    )


async def group_poke(bot: Bot, group_id: str, user_id: str) -> None:
    await _call(
        bot,
        "group_poke",
        capability=Capability.GROUP_POKE,
        group_id=group_id,
        user_id=user_id,
    )


async def send_user_like(bot: Bot, user_id: str, times: int = 10) -> None:
    if not isinstance(times, int) or isinstance(times, bool) or not 1 <= times <= 10:
        raise PlatformOperationError("invalid_request")
    await _call(
        bot,
        "send_like",
        capability=Capability.PROFILE_LIKE,
        user_id=_numeric_id(user_id),
        times=times,
    )
