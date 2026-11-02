from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="gift",
    name="社交互动",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=(
        "data/charm.json",
        "data/flower_gifts.json",
        "data/gift_inventory.json",
        "data/gift_title_stats.json",
        "data/points.json",
    ),
    privacy_level="personal",
    backup_policy="standard",
)

import random
import re
from datetime import datetime
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from mybot.common.ai_client import is_configured, prompt_completion
from mybot.common.charm import change_charm, get_group_charm_ranking
from mybot.common.gift_store import (
    GIFT_BY_ID,
    GIFT_INVENTORY_FILE,
    GIFT_NAME_INDEX,
    GIFT_POOL,
    add_gift_item,
    consume_gift_item,
    draw_daily_gift,
    get_daily_gift_shop,
    get_gift_inventory,
    purchase_daily_shop_gift,
    purchase_daily_shop_gifts,
)
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.titles import record_flight_cup_misgift, sync_user_titles
from mybot.common.user_utils import get_nickname
from mybot.common.accounting import add_points, get_points, refund_points, spend_points

from mybot.plugins._gift import storage as _gift_storage
from mybot.plugins._gift.copy import (
    DAILY_GIFT_DRAW_COST,
    DRINK_ALIASES,
    DRINK_COST,
    DRINK_STYLES,
    DRINK_SYSTEM_PROMPT,
    FLOWER_TIERS,
    SELF_TARGET_ALIASES,
    _build_drink_prompt,
    _format_charm_delta,
    _gift_menu_text,
    _inventory_summary,
    _render_daily_shop_text,
    _render_drink_menu,
    _render_flower_menu,
    _render_new_title_notice,
)
from mybot.plugins._gift.rules import (
    _ensure_drink_poem,
    _parse_flower_tier,
    _parse_gift_target,
    _resolve_drink,
    _resolve_gift_name,
    _select_shop_offer,
    calculate_tip_distribution,
)


HELP_ITEMS = (
    HelpItem("社交互动", "/礼物图鉴 - 查看礼物全册", 5),
    HelpItem("社交互动", "/礼物商城 - 每日可购三件礼物", 6),
    HelpItem("社交互动", "/购买 - 按编号或全部购入", 7),
    HelpItem("社交互动", "/抽礼物 - 每日100积分抽一份礼物", 8),
    HelpItem("社交互动", "/背包 - 查看礼物库存", 9),
    HelpItem("社交互动", "/送礼 - 从背包送出礼物", 10),
    HelpItem("社交互动", "/送花 - 表达欣赏，10积分起", 10),
    HelpItem("社交互动", "/魅力榜 - 查看魅力排行", 15),
    HelpItem("社交互动", "/打赏 - 转赠积分，收取20%手续费", 20),
    HelpItem("社交互动", "/请喝酒 - 听酒中故事，20积分", 30),
)
COMMAND_ALIASES = (
    "礼物图鉴", "礼物池", "图鉴",
    "礼物商城", "购买", "购买礼物", "买礼物", "礼物购买",
    "抽礼物", "抽奖", "扭蛋", "礼物抽奖",
    "背包", "礼物背包",
    "送礼", "赠礼", "送礼物",
    "送花", "献花", "送花花",
    "魅力榜", "魅力排行", "魅力值排行",
    "打赏", "转账", "送积分",
    "请喝酒", "请本猫喝酒", "敬酒",
)

logger = get_plugin_logger(__name__)

FLOWER_GIFTS_FILE = Path(__file__).resolve().parent.parent / "data" / "flower_gifts.json"
def _daily_flower_key(group_id: str, user_id: str) -> str:
    return _gift_storage.daily_flower_key(group_id, user_id)


def _reserve_daily_flower(
    group_id: str,
    user_id: str,
    target_id: str,
    amount: int,
    *,
    now: datetime | None = None,
) -> dict | None:
    return _gift_storage.reserve_daily_flower(
        group_id,
        user_id,
        target_id,
        amount,
        data_file=FLOWER_GIFTS_FILE,
        now=now,
    )


def _release_daily_flower(group_id: str, user_id: str, amount: int) -> None:
    _gift_storage.release_daily_flower(
        group_id,
        user_id,
        amount,
        data_file=FLOWER_GIFTS_FILE,
    )


# 礼物图鉴
gift_catalog = on_command("礼物图鉴", aliases={"礼物池", "图鉴"}, priority=5, block=True)


@gift_catalog.handle()
async def handle_gift_catalog():
    await gift_catalog.finish(_gift_menu_text())


# 礼物商城
gift_shop = on_command("礼物商城", aliases=set(), priority=5, block=True)


@gift_shop.handle()
async def handle_gift_shop(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await gift_shop.finish(
            "（拢起摊布）礼物商城按群分开摆，请到群里来逛。\n"
            "『一摊小物分群设，入席方知价与香。』"
        )

    await gift_shop.finish(_render_daily_shop_text(str(event.group_id)))


# 购买礼物
buy_gift_cmd = on_command("购买", aliases={"购买礼物", "买礼物", "礼物购买"}, priority=5, block=True)


@buy_gift_cmd.handle()
async def handle_buy_gift(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await buy_gift_cmd.finish(
            "（按住价签）礼物买卖要按群记账，请到群里来挑。\n"
            "『银钱往来须有处，入群方好定新价。』"
        )

    group_id = str(event.group_id)
    user_id = event.get_user_id()
    raw_text = args.extract_plain_text().strip()
    shop = get_daily_gift_shop(group_id, user_id)
    if not raw_text:
        await buy_gift_cmd.finish(
            f"{_render_daily_shop_text(group_id, user_id)}\n"
            "（敲了敲木牌）看中哪件，就用 /购买 1、/购买 2、/购买 3，或 /购买 全部。\n"
            "『欲买先将牌号报，免教错把别枝挑。』"
        )

    if raw_text == "全部":
        purchased_ids = set(shop.get("purchased_gift_ids", []))
        remaining_offers = [offer for offer in shop.get("offers", []) if offer["gift"]["id"] not in purchased_ids]
        if not remaining_offers:
            await buy_gift_cmd.finish(
                "（合上摊布）今日这三样你都已收下，明朝再来挑新货吧。\n"
                "『今朝小摊都买尽，只待明晨换新香。』"
            )

        total_price = sum(int(offer["price"]) for offer in remaining_offers)
        points = get_points(user_id, group_id)
        if points["current"] < total_price:
            await buy_gift_cmd.finish(
                f"（拨了拨钱袋）剩下 {len(remaining_offers)} 件一共要 {total_price} 积分，你目前只有 {points['current']} 积分。\n"
                "先攒够银钱，再来一口气包圆吧。\n"
                "『想把三枝同袖带，囊中先得有余声。』"
            )

        if not spend_points(user_id, group_id, total_price):
            await buy_gift_cmd.finish(
                "（翻账本）今日这几笔礼账一时记不上，请稍后再试。\n"
                "『账页偶逢风作乱，稍停片刻再成交。』"
            )

        try:
            result = purchase_daily_shop_gifts(
                user_id,
                group_id,
                [offer["gift"]["id"] for offer in remaining_offers],
            )
        except Exception as exc:
            refund_points(user_id, group_id, total_price)
            logger.exception(f"礼物商城批量购买写入失败 user_id={user_id} group_id={group_id}: {exc}")
            await buy_gift_cmd.finish(
                f"（按住木匣）这一摊买卖刚落笔就被风吹乱，本猫已退回 {total_price} 积分。\n"
                "『满摊欲尽风先扰，钱已归囊且再寻。』"
            )

        if result["status"] != "ok":
            refund_points(user_id, group_id, total_price)
            await buy_gift_cmd.finish(
                f"（拢住货签）这一摊买卖没能成交，本猫已退回 {total_price} 积分。\n"
                "请先重看 /礼物商城 的当日货单。\n"
                "『摊前货色随朝换，且照新牌再下钱。』"
            )

        nickname = await get_nickname(bot, user_id, context="购买礼物.全部")
        lines = [
            "🛍️ 李太白给·一口气包圆 🛍️",
            "=" * 22,
            f"（收了银钱）{nickname} 今日把摊前余下几件一并买走：",
        ]
        for item in result.get("results", []):
            gift = item["gift"]
            lines.append(f"{gift['icon']} {gift['name']} [{gift['rarity']}] - {item['price']} 积分｜库存 {item['quantity']} 件")
        lines.extend(
            [
                "=" * 22,
                f"合计花费：{result['price']} 积分",
                "『一摊星月收入袖，改日拣香赠故人。』",
            ]
        )
        await buy_gift_cmd.finish("\n".join(lines))

    offer = _select_shop_offer(shop, raw_text)
    if not offer:
        await buy_gift_cmd.finish(
            f"{_render_daily_shop_text(group_id, user_id)}\n"
            "（摊开今日货签）请输入 `/购买 1`、`/购买 2`、`/购买 3`，也可用礼物名或 `/购买 全部`。\n"
            "『牌号若明成交快，莫教错认别枝香。』"
        )

    gift = offer["gift"]
    points = get_points(user_id, group_id)
    if points["current"] < offer["price"]:
        await buy_gift_cmd.finish(
            f"（拨了拨钱袋）{gift['icon']} {gift['name']} 今日作价 {offer['price']} 积分，你目前只有 {points['current']} 积分。\n"
            "『囊中若少三分响，且等来时再换香。』"
        )

    if not spend_points(user_id, group_id, offer["price"]):
        await buy_gift_cmd.finish(
            "（翻账本）今日这笔礼账一时记不上，请稍后再试。\n"
            "『账页偶逢风作乱，稍停片刻再成交。』"
        )

    try:
        result = purchase_daily_shop_gift(user_id, group_id, gift["id"])
    except Exception as exc:
        refund_points(user_id, group_id, offer["price"])
        logger.exception(f"礼物商城购买写入失败 user_id={user_id} group_id={group_id} gift={gift['id']}: {exc}")
        await buy_gift_cmd.finish(
            f"（按住木匣）这笔买卖刚落笔就被风吹乱，本猫已退回 {offer['price']} 积分。\n"
            "『买卖未成钱已返，且等风稳再来寻。』"
        )

    if result["status"] != "ok":
        refund_points(user_id, group_id, offer["price"])
        if result["status"] == "already_purchased":
            bought = result.get("gift")
            bought_text = f"今日已买过 {bought['icon']} {bought['name']}。" if bought else "这件礼物你今日已经买过了。"
            await buy_gift_cmd.finish(
                f"（按住你的钱袋）{bought_text}\n"
                "本猫已把这笔积分原样退回。\n"
                "『同枝今日休重折，换看旁香也可亲。』"
            )
        await buy_gift_cmd.finish(
            f"（摊开货签）{gift['icon']} {gift['name']} 今日不在售，本猫已退回 {offer['price']} 积分。\n"
            "请先看 /礼物商城 的当日货单。\n"
            "『摊前货色随朝换，且照新牌再下钱。』"
        )

    nickname = await get_nickname(bot, user_id, context="购买礼物")
    await buy_gift_cmd.finish(
        f"🛍️ 李太白给·成交一件 🛍️\n"
        f"{'='*22}\n"
        f"（收了银钱）{nickname} 买下了：\n"
        f"{gift['icon']} {gift['name']} [{gift['rarity']}]\n"
        f"{gift['summary']}\n"
        f"作价：{result['price']} 积分\n"
        f"背包库存：{result['quantity']} 件\n"
        f"{'='*22}\n"
        "『今日挑得心头物，且向人间赠月光。』"
    )


# 每日抽礼物
draw_gift_cmd = on_command("抽礼物", aliases={"抽奖", "扭蛋", "礼物抽奖"}, priority=5, block=True)


@draw_gift_cmd.handle()
async def handle_draw_gift(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await draw_gift_cmd.finish(
            "（捂住抽奖匣）抽礼要按群积分开张，请到群里来抽。\n"
            "『独坐难开百样铺，入群方见满箱春。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    points = get_points(user_id, group_id)
    if points["current"] < DAILY_GIFT_DRAW_COST:
        await draw_gift_cmd.finish(
            f"（拨了拨锦囊）今日抽礼要 {DAILY_GIFT_DRAW_COST} 积分，你目前只有 {points['current']} 积分。\n"
            "『囊中未满先收手，来日风来再掷签。』"
        )

    if not spend_points(user_id, group_id, DAILY_GIFT_DRAW_COST):
        await draw_gift_cmd.finish(
            "（翻账本）抽奖匣暂时记不上账，请稍后再试。\n"
            "『账页偶逢风作乱，改日重来手更稳。』"
        )

    try:
        result = draw_daily_gift(user_id, group_id)
    except Exception as exc:
        refund_points(user_id, group_id, DAILY_GIFT_DRAW_COST)
        logger.exception(f"礼物抽奖写入失败 user_id={user_id} group_id={group_id}: {exc}")
        await draw_gift_cmd.finish(
            f"（按住抽奖匣）锦囊口忽然打结，本猫已退回 {DAILY_GIFT_DRAW_COST} 积分。\n"
            "『礼未开封钱已返，且等风顺再抽签。』"
        )

    if result["status"] != "ok":
        refund_points(user_id, group_id, DAILY_GIFT_DRAW_COST)
        gift = result.get("gift")
        gift_hint = f"上一份是 {gift['icon']} {gift['name']}。" if gift else "今日份已经记在簿上。"
        await draw_gift_cmd.finish(
            "（按住你的手腕）今日礼物已经抽过一次了，本猫把这 100 积分原样退回。\n"
            f"{gift_hint}\n"
            "『一日一抽宜有度，明朝再试手中签。』"
        )

    gift = result["gift"]
    nickname = await get_nickname(bot, user_id, context="抽礼物")
    await draw_gift_cmd.finish(
        f"🎁 李太白给·今日礼物揭晓 🎁\n"
        f"{'='*22}\n"
        f"（抖开锦囊）{nickname} 今日抽中了：\n"
        f"{gift['icon']} {gift['name']} [{gift['rarity']}]\n"
        f"{gift['summary']}\n"
        f"赠予群友：{_format_charm_delta(gift['other_charm'])} 魅力\n"
        f"{'可送自己：' + _format_charm_delta(gift['self_charm']) + ' 魅力' if gift['self_charm'] > 0 else '这件礼物更适合送给别人。'}\n"
        f"背包库存：{result['quantity']} 件\n"
        f"（已消耗 {DAILY_GIFT_DRAW_COST} 积分）\n"
        f"{'='*22}\n"
        f"『今日袖里得新巧，改向谁人递暖光。』"
    )


# 背包
gift_bag = on_command("背包", aliases={"礼物背包"}, priority=5, block=True)


@gift_bag.handle()
async def handle_gift_bag(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await gift_bag.finish(
            "（拍拍锦囊）背包按群分开记，请到群里查看。\n"
            "『囊中物事分江湖，入群再数最分明。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    nickname = await get_nickname(bot, user_id, context="背包")
    record = get_gift_inventory(user_id, group_id)
    last_draw_date = record.get("last_draw_date") or "尚未抽取"
    await gift_bag.finish(
        f"🎒 李太白给·礼物背包 🎒\n"
        f"{'='*22}\n"
        f"（抖开锦囊）{nickname} 的藏物如下：\n"
        f"上次抽取：{last_draw_date}\n"
        f"{'='*22}\n"
        f"{_inventory_summary(record)}\n"
        f"{'='*22}\n"
        f"『小物虽轻情可重，且留袖底待相逢。』"
    )


# 送礼
send_gift_cmd = on_command("送礼", aliases={"赠礼", "送礼物"}, priority=5, block=True)


@send_gift_cmd.handle()
async def handle_send_gift(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await send_gift_cmd.finish(
            "（收起锦囊）送礼要在群里见证，才有这份热闹。\n"
            "『有礼须从人海过，一声喝彩最成春。』"
        )

    raw_text = args.extract_plain_text().strip()
    target_id, gift_text = _parse_gift_target(event, raw_text)
    gift = _resolve_gift_name(gift_text)
    if not target_id or not gift:
        await send_gift_cmd.finish(
            "🎁 李太白给·送礼指南 🎁\n"
            f"{'='*22}\n"
            "用法：/送礼 @某人 礼物名\n"
            "或：/送礼 自己 礼物名\n"
            "先用 /背包 查看你现在持有的礼物。\n"
            f"{'='*22}\n"
            "『袖里有物须点名，送人送己莫含糊。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    if target_id == user_id and gift["self_charm"] <= 0:
        await send_gift_cmd.finish(
            f"（把 {gift['name']} 往回一按）这件礼物更适合送给别人，送给自己不涨魅力。\n"
            "换一件能自用的礼物再试吧。\n"
            "『好物偏宜传远客，未必都能照自身。』"
        )

    consume_result = consume_gift_item(user_id, group_id, gift["id"])
    if consume_result["status"] != "ok":
        await send_gift_cmd.finish(
            f"（翻了翻锦囊）你背包里没有 {gift['icon']} {gift['name']}。\n"
            "先去 /抽礼物 攒些存货吧。\n"
            "『囊中若少传情物，且向商铺试手风。』"
        )

    charm_gain = gift["self_charm"] if target_id == user_id else gift["other_charm"]
    try:
        change_charm(target_id, group_id, charm_gain)
    except Exception as exc:
        logger.exception(
            f"送礼魅力发放失败 sender={user_id} target={target_id} group_id={group_id} gift={gift['id']}: {exc}"
        )
        try:
            add_gift_item(user_id, group_id, gift["id"], 1)
        except Exception as rollback_exc:
            logger.exception(
                f"送礼库存回滚失败 sender={user_id} group_id={group_id} gift={gift['id']}: {rollback_exc}"
            )
        await send_gift_cmd.finish(
            "（按住礼盒）这份心意刚要送出就被风吹乱了，请稍后再试。\n"
            "『礼到半途风作梗，待云散尽再相传。』"
        )

    if gift["id"] == "flight_cup" and target_id != user_id:
        title_status = None
        try:
            record_flight_cup_misgift(user_id, group_id)
            title_status = sync_user_titles(user_id, group_id, get_points(user_id, group_id))
        except Exception as exc:
            logger.exception(
                f"✈杯隐藏成就记录失败 sender={user_id} target={target_id} group_id={group_id}: {exc}"
            )
    else:
        title_status = None

    sender_name = await get_nickname(bot, user_id, context="送礼.sender")
    target_name = await get_nickname(bot, target_id, context="送礼.target")
    remain_text = f"背包余量：{consume_result['quantity']} 件"
    action_text = "自己收下" if target_id == user_id else f"送给了 {target_name}"
    new_title_text = _render_new_title_notice(title_status)
    await send_gift_cmd.finish(
        f"{gift['icon']} {gift['name']} 已送达\n"
        f"{'='*22}\n"
        f"（理了理缎带）{sender_name} 把 {gift['name']} {action_text}。\n"
        f"{target_name if target_id != user_id else sender_name} 魅力值 {_format_charm_delta(charm_gain)}\n"
        f"{remain_text}\n"
        f"{new_title_text + chr(10) if new_title_text else ''}"
        f"{'='*22}\n"
        f"『礼轻也可摇星色，送到心头便有光。』"
    )


# 送花
send_flower = on_command("送花", aliases={"献花", "送花花"}, priority=5, block=True)

@send_flower.handle()
async def handle_flower(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await send_flower.finish(
            "（摇头）送花要在群里才浪漫，旁人见证才算花开。\n"
            "『一枝花落无人见，不如群中赠有缘。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)

    # 解析@的人
    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq"))
            break

    raw_text = args.extract_plain_text().strip()
    tier = _parse_flower_tier(raw_text)
    if not target_id or tier is None:
        invalid_tier = raw_text if target_id and raw_text else ""
        await send_flower.finish(_render_flower_menu(invalid_tier))

    if target_id == user_id:
        await send_flower.finish(
            "（扶额）今日这朵花应赠有缘人，自己收下可不算数。\n"
            "『花向他人开一度，余香才肯到君前。』"
        )

    # 检查积分
    points = get_points(user_id, group_id)
    if points["current"] < tier:
        await send_flower.finish(
            f"（合上花匣）这朵花需要 {tier} 积分，你目前只有 {points['current']} 积分。\n"
            "『囊中暂少三分墨，来日花开再赠君。』"
        )

    previous = _reserve_daily_flower(group_id, user_id, target_id, tier)
    if previous:
        await send_flower.finish(
            "（指向今日花笺）你今天已经送过一份花礼了，明日再来吧。\n"
            "『一日一花情不滥，明朝仍有满园春。』"
        )

    if not spend_points(user_id, group_id, tier):
        _release_daily_flower(group_id, user_id, tier)
        await send_flower.finish(
            "（翻了翻账本）这朵花暂时记不上账，请稍后再试。\n"
            "『账页风来花未落，稍停片刻再传情。』"
        )

    reward = FLOWER_TIERS[tier]["reward"]
    charm = FLOWER_TIERS[tier]["charm"]
    charm_added = False
    try:
        change_charm(target_id, group_id, charm)
        charm_added = True
        add_points(target_id, group_id, reward)
    except Exception as exc:
        refund_points(user_id, group_id, tier)
        if charm_added:
            try:
                change_charm(target_id, group_id, -charm)
            except Exception as rollback_exc:
                logger.exception(
                    f"送花魅力回滚失败 target={target_id} group_id={group_id}: {rollback_exc}"
                )
        _release_daily_flower(group_id, user_id, tier)
        logger.exception(
            f"送花奖励发放失败 sender={user_id} target={target_id} group_id={group_id} tier={tier}: {exc}"
        )
        await send_flower.finish(
            f"（护住花枝）花路忽遇风雨，本猫已退回 {tier} 积分，请稍后再赠。\n"
            "『花未到时钱已返，待晴再寄一枝春。』"
        )

    sender_name = await get_nickname(bot, user_id, context="送花.sender")
    target_name = await get_nickname(bot, target_id, context="送花.target")
    flower = FLOWER_TIERS[tier]["flower"]
    flower_name = FLOWER_TIERS[tier]["name"]
    message = random.choice(FLOWER_TIERS[tier]["messages"]).format(
        sender=sender_name,
        target=target_name,
    )
    poem = FLOWER_TIERS[tier]["poem"]

    await send_flower.finish(
        f"{flower} {flower_name}已送达 {flower}\n"
        f"{'='*20}\n"
        f"{message}\n"
        f"{'='*20}\n"
        f"{target_name} 获得 {reward} 积分\n"
        f"{target_name} 魅力值 +{charm}\n"
        f"{poem}"
    )


# 魅力排行榜
charm_ranking = on_command("魅力榜", aliases={"魅力排行", "魅力值排行"}, priority=5, block=True)


@charm_ranking.handle()
async def handle_charm_ranking(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await charm_ranking.finish(
            "（收起花名册）魅力榜只记录群中花事，请到群里查看。\n"
            "『花名须在群中记，独坐难评第一枝。』"
        )

    group_id = str(event.group_id)
    records = get_group_charm_ranking(group_id)
    if not records:
        await charm_ranking.finish(
            "🌸 李太白给·魅力榜 🌸\n"
            "====================\n"
            "（翻开空白花名册）本群尚无人积攒魅力。\n"
            "『榜上如今花未著，且看谁先得一枝。』"
        )

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for index, record in enumerate(records):
        nickname = await get_nickname(bot, record["user_id"], context="魅力榜")
        if len(nickname) > 10:
            nickname = nickname[:9] + "…"
        rank = medals[index] if index < len(medals) else f"{index + 1}."
        lines.append(f"{rank} {nickname}：{record['charm']} 魅力")

    await charm_ranking.finish(
        "🌸 李太白给·魅力榜 🌸\n"
        "====================\n"
        "（展开花名册）本群群芳次第如下：\n"
        "====================\n"
        f"{chr(10).join(lines)}\n"
        "====================\n"
        "『花有千般颜色好，人因情意上高台。』"
    )


# 打赏
tip_user = on_command("打赏", aliases={"转账", "送积分"}, priority=5, block=True)

@tip_user.handle()
async def handle_tip(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await tip_user.finish(
            "（合上账本）打赏要在群中见证，私下银钱本猫不记。\n"
            "『群中往来群中记，一笔真情众人知。』"
        )
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    
    # 解析@的人和金额
    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq"))
            break
    
    # 解析金额
    text = args.extract_plain_text().strip()
    amount = 0
    nums = re.findall(r'\d+', text)
    if nums:
        amount = int(nums[0])
    
    if not target_id or amount <= 0:
        await tip_user.finish(
            f"💰 打赏功能 💰\n"
            f"{'='*20}\n"
            f"用法：/打赏 @某人 金额\n"
            f"例如：/打赏 @小明 50\n"
            f"金额须为 5 至 1000，并且是 5 的倍数。\n"
            f"收取 20% 手续费，对方获得剩余 80%。\n"
            f"{'='*20}\n"
            f"『银钱来往须明账，八分赠友二分藏。』"
        )
    
    if target_id == user_id:
        await tip_user.finish(
            "（扶额）自己打赏自己，只是把积分从左袖放进右袖。\n"
            "『银钱绕袖终归己，不若赠人留暖香。』"
        )
    
    if amount < 5 or amount > 1000 or amount % 5 != 0:
        await tip_user.finish(
            "（拨动算盘）打赏金额须为 5 至 1000，并且是 5 的倍数。\n"
            "『五五成行账好算，二分入库八分传。』"
        )
    
    # 检查积分
    points = get_points(user_id, group_id)
    if points["current"] < amount:
        await tip_user.finish(
            f"（轻拨算盘）你目前只有 {points['current']} 积分，不够打赏 {amount} 积分。\n"
            "『囊中暂少传情物，来日丰盈再赠君。』"
        )
    
    fee, received = calculate_tip_distribution(amount)
    if not spend_points(user_id, group_id, amount):
        await tip_user.finish(
            "（算盘一停）这笔打赏银钱暂时落不了账，请重新查看积分后再试。\n"
            "『账上珠声忽一乱，稍停片刻再传情。』"
        )

    try:
        add_points(target_id, group_id, received)
    except Exception as exc:
        refund_points(user_id, group_id, amount)
        logger.exception(
            f"打赏发放失败 sender={user_id} target={target_id} group_id={group_id} amount={amount}: {exc}"
        )
        await tip_user.finish(
            f"（合上账本）打赏未能送达，本猫已退回 {amount} 积分。\n"
            "『银钱未渡风波里，原数归囊待再传。』"
        )
    
    sender_name = await get_nickname(bot, user_id, context="打赏.sender")
    target_name = await get_nickname(bot, target_id, context="打赏.target")
    
    await tip_user.finish(
        f"💰 打赏成功 💰\n"
        f"{'='*20}\n"
        f"（鼓掌）{sender_name} 豪气地打赏了 {target_name}\n"
        f"{'='*20}\n"
        f"💎 支出：{amount} 积分\n"
        f"🎁 对方到账：{received} 积分\n"
        f"🧾 手续费：{fee} 积分（20%）\n"
        f"{'='*20}\n"
        f"『慷慨解囊显真情，\n八分赠友二分留。\n{sender_name}今日真大方，\n本猫替你记风流~』"
    )

# 请喝酒
treat_drink = on_command("请喝酒", aliases={"请本猫喝酒", "敬酒"}, priority=5, block=True)

@treat_drink.handle()
async def handle_drink(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await treat_drink.finish(
            "（摇头）故事酒要在群里请，独饮可听不见满桌回声。\n"
            "『一人杯浅故事短，众友同席夜方长。』"
        )

    raw_drink = args.extract_plain_text().strip()
    drink_name = _resolve_drink(raw_drink)
    if not drink_name:
        await treat_drink.finish(_render_drink_menu(raw_drink))

    user_id = event.get_user_id()
    group_id = str(event.group_id)

    if not is_configured():
        await treat_drink.finish(
            "（揭开空酒坛）故事酒馆今日尚未接通后厨，积分先替你留着。\n"
            "『杯中故事仍封坛，待得春风再启谈。』"
        )

    # 检查积分
    points = get_points(user_id, group_id)
    if points["current"] < DRINK_COST:
        await treat_drink.finish(
            f"（轻轻盖回酒坛）一杯故事酒要 {DRINK_COST} 积分，你目前只有 {points['current']} 积分。\n"
            "『酒香且候囊中满，来日同斟月一弯。』"
        )

    # 扣积分
    if not spend_points(user_id, group_id, DRINK_COST):
        await treat_drink.finish(
            "（翻了翻账本）这杯酒暂时记不上账，请稍后再试。\n"
            "『账页偶逢风作乱，酒杯且待墨痕干。』"
        )

    nickname = await get_nickname(bot, user_id, context="请喝酒")
    drink = DRINK_STYLES[drink_name]

    try:
        story = await prompt_completion(
            _build_drink_prompt(nickname, drink_name),
            system=DRINK_SYSTEM_PROMPT,
            max_tokens=900,
            temperature=0.95,
            timeout=60,
        )
        if not story:
            raise RuntimeError("empty drink story")
        story = _ensure_drink_poem(story, drink_name)
    except Exception as exc:
        refund_points(user_id, group_id, DRINK_COST)
        logger.exception(
            f"请喝酒故事生成失败 user_id={user_id} group_id={group_id} drink={drink_name}: {exc}"
        )
        await treat_drink.finish(
            f"（扶住酒坛）这杯{drink_name}香气正好，故事却被风吹散了；"
            f"本猫已退回 {DRINK_COST} 积分。\n"
            "『酒未成篇钱已还，待风停后再同欢。』"
        )

    await treat_drink.finish(
        f"{drink['icon']} 李太白给·{drink_name}故事 {drink['icon']}\n"
        f"{'='*20}\n"
        f"（收下 {nickname} 递来的{drink_name}，本猫缓缓开口）\n"
        f"（消耗 {DRINK_COST} 积分）\n"
        f"{'='*20}\n"
        f"{story}"
    )
