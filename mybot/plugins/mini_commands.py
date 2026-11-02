from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="mini_commands",
    name="彩蛋小令",
    default_enabled=True,
    scope="group",
    permission_level=2,
    data_files=(
        "data/charm.json",
        "data/fortune_data.json",
        "data/gift_inventory.json",
        "data/titles.json",
    ),
    privacy_level="personal",
    backup_policy="standard",
)

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

from mybot.common.charm import change_charm
from mybot.common.gift_store import GIFT_BY_ID, add_gift_item, consume_gift_item
from mybot.common.logger import get_plugin_logger
from mybot.common.streak import today_fortune_has_yi_item
from mybot.common.titles import grant_title
from mybot.common.user_utils import get_nickname


COMMAND_ALIASES = ("起飞",)
PUBLIC_COMMANDS = COMMAND_ALIASES

FLIGHT_CUP_ID = "flight_cup"
CHINA_CAPTAIN_TITLE_ID = "secret_china_captain"

logger = get_plugin_logger(__name__)


def _format_charm_delta(amount: int) -> str:
    return f"{amount:+d}"


def use_flight_cup_on_self(user_id: str, group_id: str) -> dict:
    gift = GIFT_BY_ID[FLIGHT_CUP_ID]
    consume_result = consume_gift_item(user_id, group_id, gift["id"])
    if consume_result["status"] != "ok":
        return {
            "status": "missing",
            "gift": gift,
            "quantity": consume_result.get("quantity", 0),
        }

    charm_gain = int(gift["self_charm"])
    try:
        charm_record = change_charm(user_id, group_id, charm_gain)
    except Exception:
        try:
            add_gift_item(user_id, group_id, gift["id"], 1)
        except Exception as rollback_exc:
            logger.exception(
                f"起飞库存回滚失败 user_id={user_id} group_id={group_id} gift={gift['id']}: {rollback_exc}"
            )
        raise

    return {
        "status": "ok",
        "gift": gift,
        "quantity": consume_result["quantity"],
        "charm_gain": charm_gain,
        "charm": int(charm_record.get("charm", 0)),
    }


def grant_china_captain_if_eligible(user_id: str, group_id: str):
    if not today_fortune_has_yi_item(user_id, group_id, "起飞"):
        return None
    return grant_title(user_id, group_id, CHINA_CAPTAIN_TITLE_ID)


flight = on_command("起飞", priority=5, block=True)


@flight.handle()
async def handle_flight(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await flight.finish(
            "（把杯口一扣）这阵风要在群里起，独坐书房飞不远。\n"
            "『杯中有风须众看，一人扶摇少些声。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    try:
        result = use_flight_cup_on_self(user_id, group_id)
    except Exception as exc:
        logger.exception(f"起飞失败 user_id={user_id} group_id={group_id}: {exc}")
        await flight.finish(
            "（按住杯盏）风刚起便乱了章法，稍后再试。\n"
            "『杯影未稳云先散，待得清风再上天。』"
        )

    gift = result["gift"]
    if result["status"] == "missing":
        await flight.finish(
            f"（翻了翻锦囊）杯影未见，阁下背包里没有 {gift['icon']} {gift['name']}。\n"
            "先去 /抽礼物 或礼物商城碰碰手气吧。\n"
            "『袖里无杯风不起，且向摊前试手来。』"
        )

    nickname = await get_nickname(bot, user_id, context="起飞")
    hidden_title_text = ""
    hidden_title = grant_china_captain_if_eligible(user_id, group_id)
    if hidden_title:
        hidden_title_text = f"\n🎖 天外名号：{hidden_title.title} 已入册"

    await flight.finish(
        f"{gift['icon']} 起飞成功\n"
        f"{'='*22}\n"
        f"（{nickname} 把 {gift['name']} 往掌心一托，杯底忽然生风。）\n"
        f"魅力值 {_format_charm_delta(result['charm_gain'])}\n"
        f"背包余量：{result['quantity']} 件\n"
        f"{'='*22}{hidden_title_text}\n"
        "『杯中忽起三千浪，\n"
        "扶摇一瞬过云廊。\n"
        "本猫墨镜刚扶稳，\n"
        "君已乘风到月旁。』"
    )
