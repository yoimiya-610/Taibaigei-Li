from mybot.common.plugin_metadata import declare_plugin


PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="profile_like",
    name="墨赞名片",
    default_enabled=True,
    scope="group",
    permission_level=2,
    privacy_level="public",
    backup_policy="none",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

from mybot.common.group_platform import send_user_like
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.message_utils import get_first_at_user_id


LIKE_TIMES = 10
HELP_ITEMS = (
    HelpItem("社交互动", "/墨赞 - 给群友资料卡落十枚墨赞", 25),
)
COMMAND_ALIASES = ("墨赞", "点赞", "赞名片", "资料卡点赞")

NON_GROUP_MESSAGE = (
    "（把墨盒收回袖中）墨赞要当着群友落印，请到群里用 /墨赞 @群友。\n"
    "『孤席名帖无从觅，\n"
    "还向群中认故人。\n"
    "待得一声相唤起，\n"
    "本猫落爪点花痕。』"
)
MISSING_TARGET_MESSAGE = (
    "（本猫举爪等了半晌）要给谁落这份墨赞？请用 /墨赞 @群友 指明一位。\n"
    "『名帖无题难落笔，\n"
    "且将一友指猫前。\n"
    "墨花十点随爪下，\n"
    "替你轻夸一整天。』"
)
SELF_TARGET_MESSAGE = (
    "（对着自己的名帖端详片刻）本猫不能给自家落赞，换一位群友吧。\n"
    "『自夸终觉墨痕浅，\n"
    "好意还须赠故人。\n"
    "且把名帖重新指，\n"
    "本猫替你点春痕。』"
)
FAILED_MESSAGE = (
    "（爪尖刚触名帖，墨痕却被门槛拦住。）今日的赞也许已满，"
    "或这张名帖暂未开门，稍后再试。\n"
    "『墨痕欲落风先起，\n"
    "名帖轻阖暂不传。\n"
    "待到云开重展卷，\n"
    "本猫还来续十赞。』"
)

logger = get_plugin_logger(__name__)


def extract_profile_like_target(message: Message) -> str | None:
    """Read one concrete QQ id from OneBot at segments only."""
    target_id = get_first_at_user_id(message)
    if target_id is None:
        return None
    normalized = target_id.strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        return None
    return str(int(normalized))


def build_profile_like_success(target_id: str) -> Message:
    return Message(
        [
            MessageSegment.text("（墨镜一推，本猫抬爪在 "),
            MessageSegment.at(int(target_id)),
            MessageSegment.text(
                " 的资料卡上连落十枚梅花墨印。）\n"
                "墨赞已成：10 次\n"
                "『爪底轻敲云外帖，\n"
                "十痕梅印落君前。\n"
                "休言好意无凭据，\n"
                "本猫替君把名传。』"
            ),
        ]
    )


profile_like = on_command(
    "墨赞",
    aliases={"点赞", "赞名片", "资料卡点赞"},
    priority=5,
    block=True,
)


@profile_like.handle()
async def handle_profile_like(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
):
    if not isinstance(event, GroupMessageEvent):
        await profile_like.finish(NON_GROUP_MESSAGE)

    target_id = extract_profile_like_target(args)
    if target_id is None:
        await profile_like.finish(MISSING_TARGET_MESSAGE)
    if target_id == str(bot.self_id):
        await profile_like.finish(SELF_TARGET_MESSAGE)

    try:
        await send_user_like(bot, target_id, LIKE_TIMES)
    except Exception as exc:
        logger.exception(
            "墨赞名片失败 "
            f"group_id={event.group_id} user_id={event.get_user_id()} "
            f"target_id={target_id}: {exc}"
        )
        await profile_like.finish(FAILED_MESSAGE)

    await profile_like.finish(build_profile_like_success(target_id))
