from pathlib import Path
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg

from mybot.common.help_registry import HelpItem
from mybot.common.json_store import load_json, mutate_json, save_json
from mybot.common.streak import get_current_streak, get_streak_evaluation
from mybot.common.titles import (
    clear_equipped_title,
    equip_title,
    get_display_title,
    get_new_title_achievements,
    render_title_detail,
    render_title_list,
    sync_user_titles,
)
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("签到积分", "/积分 - 查看积分", 20),
    HelpItem("签到积分", "/称号 - 查看成就称号", 25),
    HelpItem("签到积分", "/称号说明 - 查看单个称号说明", 26),
    HelpItem("签到积分", "/排行榜 - 积分排行", 30),
)
COMMAND_ALIASES = (
    "积分", "查积分", "我的积分",
    "称号", "成就", "成就称号", "称号列表",
    "称号说明", "成就说明",
    "佩戴称号", "更换称号", "戴称号", "卸下称号", "取消称号",
    "排行榜", "积分排行", "积分榜", "富豪榜",
)


# 积分数据文件路径
POINTS_FILE = Path(__file__).resolve().parent.parent / "data" / "points.json"

# 确保数据目录存在
POINTS_FILE.parent.mkdir(parents=True, exist_ok=True)

def load_points() -> dict:
    """加载积分数据"""
    return load_json(POINTS_FILE, {})

def save_points(data: dict):
    """保存积分数据"""
    save_json(POINTS_FILE, data)


def _new_points_record(user_id: str, group_id: str) -> dict:
    return {"current": 0, "total": 0, "user_id": user_id, "group_id": group_id}

def get_points(user_id: str, group_id: str) -> dict:
    """获取用户积分"""
    key = f"{group_id}_{user_id}"

    def mutator(data: dict) -> dict:
        if key not in data:
            data[key] = _new_points_record(user_id, group_id)
        return dict(data[key])

    return mutate_json(POINTS_FILE, {}, mutator)

def add_points(user_id: str, group_id: str, amount: int) -> dict:
    """增加积分"""
    key = f"{group_id}_{user_id}"

    def mutator(data: dict) -> dict:
        if key not in data:
            data[key] = _new_points_record(user_id, group_id)

        data[key]["current"] += amount
        if amount > 0:
            data[key]["total"] += amount
        return dict(data[key])

    return mutate_json(POINTS_FILE, {}, mutator)


def add_points_once(user_id: str, group_id: str, amount: int, tx_id: str) -> dict:
    """按交易号增加积分；同一交易号重复提交不会重复入账。"""
    key = f"{group_id}_{user_id}"

    def mutator(data: dict) -> dict:
        if key not in data:
            data[key] = _new_points_record(user_id, group_id)

        transactions = data[key].setdefault("transactions", [])
        if not isinstance(transactions, list):
            transactions = []
            data[key]["transactions"] = transactions
        if tx_id in transactions:
            return {"applied": False, "record": dict(data[key])}

        data[key]["current"] += amount
        if amount > 0:
            data[key]["total"] += amount
        transactions.append(tx_id)
        return {"applied": True, "record": dict(data[key])}

    return mutate_json(POINTS_FILE, {}, mutator)

def spend_points(user_id: str, group_id: str, amount: int) -> bool:
    """消费积分"""
    key = f"{group_id}_{user_id}"

    def mutator(data: dict) -> bool:
        if key not in data:
            return False
        if data[key]["current"] < amount:
            return False
        data[key]["current"] -= amount
        return True

    return mutate_json(POINTS_FILE, {}, mutator)

def refund_points(user_id: str, group_id: str, amount: int) -> dict:
    """退还积分，只恢复当前积分，不增加累计获得"""
    key = f"{group_id}_{user_id}"

    def mutator(data: dict) -> dict:
        if key not in data:
            data[key] = _new_points_record(user_id, group_id)

        data[key]["current"] += amount
        return dict(data[key])

    return mutate_json(POINTS_FILE, {}, mutator)

def get_group_ranking(group_id: str, limit: int = 10) -> list:
    """获取群组积分排行榜"""
    data = load_points()
    
    # 筛选该群组的用户
    group_users = []
    for key, value in data.items():
        if value.get("group_id") == group_id:
            group_users.append({
                "user_id": value.get("user_id"),
                "current": value.get("current", 0),
                "total": value.get("total", 0),
            })
    
    # 按当前积分排序
    group_users.sort(key=lambda x: x["current"], reverse=True)
    
    return group_users[:limit]


def _event_group_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return "private"


# 查询积分命令
check_points = on_command("积分", aliases={"查积分", "我的积分"}, priority=5, block=True)

@check_points.handle()
async def handle_check_points(bot: Bot, event: MessageEvent):
    user_id = event.get_user_id()
    group_id = _event_group_id(event)
    points_info = get_points(user_id, group_id)
    title_status = sync_user_titles(user_id, group_id, points_info)
    title_info = get_display_title(user_id, group_id, points_info)
    normal_new_titles = [achievement.title for achievement in get_new_title_achievements(title_status, hidden_only=False)]
    hidden_new_titles = [achievement.title for achievement in get_new_title_achievements(title_status, hidden_only=True)]
    new_title_text = ""
    if normal_new_titles:
        new_title_text += f"✨ 新解锁称号：{'、'.join(normal_new_titles)}\n"
    if hidden_new_titles:
        new_title_text += f"🎖 天外名号：{'、'.join(hidden_new_titles)} 已入册\n"

    if isinstance(event, GroupMessageEvent):
        streak_count = get_current_streak(user_id, group_id)
        streak_text = f"🔥 连续签到：{streak_count} 天\n💬 签到评语：{get_streak_evaluation(streak_count)}\n"
    else:
        streak_text = "🔥 连续签到：请在群内查看\n"

    nickname = await get_nickname(bot, user_id, context="积分")
    
    await check_points.finish(
        f"💰 李太白给·积分查询 💰\n"
        f"{'='*20}\n"
        f"（翻开账本）让本猫看看你今日囊中几何。\n"
        f"{'='*20}\n"
        f"👤 用户：{nickname}\n"
        f"🏷️ 称号：{title_info['title']}\n"
        f"🎖️ 名号入册：{title_info['unlocked_count']}/{title_info['total_count']}\n"
        f"💎 当前积分：{points_info['current']}\n"
        f"📊 累计获得：{points_info['total']}\n"
        f"{new_title_text}"
        f"{streak_text}"
        f"『账本不必翻太厚，够用便是好风流。』"
    )


title_list = on_command("称号", aliases={"成就", "成就称号", "称号列表"}, priority=5, block=True)
title_detail_cmd = on_command("称号说明", aliases={"成就说明"}, priority=5, block=True)


@title_list.handle()
async def handle_title_list(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await title_list.finish(
            "（合上名册）称号按群分别记录，请到群里查看。\n"
            "『名号需在江湖挂，独坐书房少些风。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    points_info = get_points(user_id, group_id)
    await title_list.finish(render_title_list(user_id, group_id, points_info))


@title_detail_cmd.handle()
async def handle_title_detail(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await title_detail_cmd.finish(
            "（合上名册）称号按群分别记录，请到群里查看。\n"
            "『名号生在江湖里，离了人群便难明。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    raw_text = args.extract_plain_text().strip()
    identifier = raw_text
    points_info = get_points(user_id, group_id)
    detail = render_title_detail(identifier, user_id, group_id, points_info)
    if not detail:
        await title_detail_cmd.finish(
            "（翻了两页）没认出这个称号。\n"
            "用法：/称号说明 称号名，可先用 /称号 看总册。\n"
            "『若问名号何处寻，先把册页从头翻。』"
        )

    await title_detail_cmd.finish(detail)


equip_title_cmd = on_command("佩戴称号", aliases={"更换称号", "戴称号"}, priority=5, block=True)


@equip_title_cmd.handle()
async def handle_equip_title(event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await equip_title_cmd.finish(
            "（抖开空袖）称号要在群里佩戴才响亮。\n"
            "『独处无须挂名号，入群方见一身风。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    raw_title = args.extract_plain_text().strip()
    points_info = get_points(user_id, group_id)
    if not raw_title:
        await equip_title_cmd.finish(
            "🎖 李太白给·佩戴称号 🎖\n"
            "====================\n"
            "（拎起名牌瞧了瞧）要挂哪块名号，先报给本猫。\n"
            "====================\n"
            "用法：/佩戴称号 称号名\n"
            "先用 /称号 看名册，需要细则可用 /称号说明 称号名。\n"
            "『衣上若无三分墨，怎知阁下哪路风。』"
        )

    if raw_title in {"默认", "无", "卸下", "取消"}:
        clear_equipped_title(user_id, group_id, points_info)
        await equip_title_cmd.finish(
            "（替你摘下名牌）衣襟暂且清爽，名号仍在册中。\n"
            "『名号暂收袖中去，清风仍识旧诗人。』"
        )

    achievement = equip_title(user_id, group_id, raw_title, points_info)
    if not achievement:
        await equip_title_cmd.finish(
            "（翻遍名册）没找到这个已解锁称号。\n"
            "请先用 /称号 查看可佩戴列表。\n"
            "『未入囊中休挂剑，先把功名慢慢攒。』"
        )

    await equip_title_cmd.finish(
        "🎖 称号佩戴成功 🎖\n"
        "====================\n"
        "（替你端端正正挂好）这回走进群里，便算有了名号。\n"
        "====================\n"
        f"当前称号：{achievement.title}\n"
        "『新名挂在衣襟上，群里行来便带风。』"
    )


clear_title_cmd = on_command("卸下称号", aliases={"取消称号"}, priority=5, block=True)


@clear_title_cmd.handle()
async def handle_clear_title(event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await clear_title_cmd.finish(
            "（收起名册）称号按群记录，请到群里操作。\n"
            "『名号要在人前卸，独坐窗边不作数。』"
        )

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    clear_equipped_title(user_id, group_id, get_points(user_id, group_id))
    await clear_title_cmd.finish(
        "（拂去衣襟名牌）已卸下手动佩戴称号。\n"
        "名号不挂在外，风流仍记账中。\n"
        "『去名不去风流意，仍是群中旧故人。』"
    )


# 排行榜命令
ranking = on_command("排行榜", aliases={"积分排行", "积分榜", "富豪榜"}, priority=5, block=True)

@ranking.handle()
async def handle_ranking(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await ranking.finish("（摇头）排行榜要在群里查看哦~")
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    # 获取排行榜
    top_users = get_group_ranking(group_id, 10)
    
    if not top_users:
        await ranking.finish(
            f"🏆 李太白给·积分排行榜 🏆\n"
            f"{'='*20}\n"
            f"（展开空榜）眼下还无人题名，快去签到落墨吧。\n"
            f"{'='*20}\n"
            f"暂无数据，快去签到赚积分吧~"
        )
    
    # 构建排行榜文本
    rank_text = []
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user in enumerate(top_users):
        nickname = await get_nickname(bot, user["user_id"], context="排行榜")
        
        # 限制昵称长度
        if len(nickname) > 8:
            nickname = nickname[:7] + "…"
        
        if i < 3:
            medal = medals[i]
        else:
            medal = f"{i+1}."
        
        rank_text.append(f"{medal} {nickname}：{user['current']} 积分")
    
    # 查找当前用户排名
    my_rank = None
    my_points = None
    all_users = get_group_ranking(group_id, 100)
    for i, user in enumerate(all_users):
        if user["user_id"] == user_id:
            my_rank = i + 1
            my_points = user["current"]
            break
    
    my_rank_text = ""
    if my_rank:
        my_rank_text = f"\n📍 你在第{my_rank}名（{my_points}积分）"

    await ranking.finish(
        f"🏆 李太白给·积分排行榜 🏆\n"
        f"{'='*20}\n"
        f"（展开金榜）诸位今日的身家，都写在这卷上了。\n"
        f"{'='*20}\n"
        f"{chr(10).join(rank_text)}"
        f"{my_rank_text}\n"
        f"『榜上高低且随它，日日有分自成名。』"
    )

