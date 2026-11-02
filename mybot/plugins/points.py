from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="points",
    name="积分排行",
    default_enabled=True,
    scope="group",
    permission_level=3,
    data_files=("data/points.json", "data/titles.json"),
    privacy_level="personal",
    backup_policy="standard",
)

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, Bot, GroupMessageEvent
from nonebot.params import CommandArg

from mybot.common.accounting import (
    add_points as accounting_add_points,
    add_points_once as accounting_add_points_once,
    get_points as accounting_get_points,
    refund_points as accounting_refund_points,
    spend_points as accounting_spend_points,
)
from mybot.common.ai_public_play_guides import PublicPlayGuideEntry
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
    HelpItem("签到积分", "/低保 - 低于100积分每日领100积分", 35),
)
COMMAND_ALIASES = (
    "积分", "查积分", "我的积分", "查分", "余额", "我的余额",
    "称号", "成就", "成就称号", "称号列表",
    "称号说明", "成就说明",
    "佩戴称号", "更换称号", "戴称号", "卸下称号", "取消称号",
    "排行榜", "排行", "积分排行", "积分榜", "富豪榜",
    "低保", "领取低保", "低保领取",
)


# 积分数据文件路径
POINTS_FILE = Path(__file__).resolve().parent.parent / "data" / "points.json"
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
LOW_INCOME_THRESHOLD = 100
LOW_INCOME_REWARD = 100
LOW_INCOME_DATE_FIELD = "last_low_income_date"

PUBLIC_PLAY_GUIDES = (
    PublicPlayGuideEntry(
        key="points_account",
        keywords=("积分", "余额", "排行榜", "积分榜", "富豪榜", "查分"),
        intents=("怎么查", "查看", "查询", "命令", "规则", "累计", "当前", "排行"),
        public_explanation=(
            "积分按群分别记账，/积分 会显示当前积分、累计获得、连续签到和称号概况；"
            "/排行榜 按本群累计获得积分排序，当前积分只作同分时的参考。"
        ),
        related_commands=("/积分", "/排行榜"),
    ),
    PublicPlayGuideEntry(
        key="low_income",
        keywords=("低保", "不足百", "不足100", "低于100", "领保"),
        intents=("怎么领", "领取", "规则", "条件", "多少", "每天", "每日", "命令"),
        public_explanation=(
            f"低保给当前积分低于 {LOW_INCOME_THRESHOLD} 的诗友每日领取一次；"
            f"成功后本猫添上 {LOW_INCOME_REWARD} 积分，并计入累计获得。"
        ),
        related_commands=("/低保", "/积分"),
    ),
    PublicPlayGuideEntry(
        key="personal_realtime_status",
        keywords=("积分", "余额", "酒钱", "签到", "低保", "称号", "名号", "魅力", "礼物", "公开贡献", "今天"),
        intents=("我有多少", "当前多少", "还剩多少", "今天签过", "领过", "我的称号", "我的状态"),
        public_explanation=(
            "普通群聊里明确询问本人积分、今日签到或礼物背包时，本猫可以从当前群的只读卷册据实回答；"
            "不能查询他人或其他群，也不能代为签到、送礼或改动状态。/我的卷册 可查看更完整的本人总览。"
        ),
        related_commands=("/我的卷册", "/积分", "/酒钱", "/称号", "/低保", "/签到"),
    ),
)

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


def current_date_text() -> str:
    return datetime.now(APP_TIMEZONE).date().isoformat()


def get_points(user_id: str, group_id: str) -> dict:
    """获取用户积分"""
    return accounting_get_points(user_id, group_id, store_path=POINTS_FILE)

def add_points(user_id: str, group_id: str, amount: int) -> dict:
    """增加积分"""
    return accounting_add_points(user_id, group_id, amount, store_path=POINTS_FILE)


def add_points_once(user_id: str, group_id: str, amount: int, tx_id: str) -> dict:
    """按交易号增加积分；同一交易号重复提交不会重复入账。"""
    return accounting_add_points_once(user_id, group_id, amount, tx_id, store_path=POINTS_FILE)

def spend_points(user_id: str, group_id: str, amount: int) -> bool:
    """消费积分"""
    return accounting_spend_points(user_id, group_id, amount, store_path=POINTS_FILE)

def refund_points(user_id: str, group_id: str, amount: int) -> dict:
    """退还积分，只恢复当前积分，不增加累计获得"""
    return accounting_refund_points(user_id, group_id, amount, store_path=POINTS_FILE)


def claim_low_income(user_id: str, group_id: str, today: str | None = None) -> dict:
    """领取低保：当前积分低于阈值时每日固定入账一次。"""
    key = f"{group_id}_{user_id}"
    claim_date = today or current_date_text()

    def mutator(data: dict) -> dict:
        if key not in data:
            data[key] = _new_points_record(user_id, group_id)

        record = data[key]
        if record.get(LOW_INCOME_DATE_FIELD) == claim_date:
            return {"status": "already_claimed", "amount": 0, "record": dict(record)}

        current = int(record.get("current", 0))
        if current >= LOW_INCOME_THRESHOLD:
            return {"status": "ineligible", "amount": 0, "record": dict(record)}

        record["current"] = current + LOW_INCOME_REWARD
        record["total"] = int(record.get("total", 0)) + LOW_INCOME_REWARD
        record[LOW_INCOME_DATE_FIELD] = claim_date
        return {"status": "claimed", "amount": LOW_INCOME_REWARD, "record": dict(record)}

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
    
    # 按历史累计积分排序，当前积分只作为同累计时的辅助口径。
    group_users.sort(key=lambda x: (x["total"], x["current"]), reverse=True)
    
    return group_users[:limit]


def _event_group_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return str(event.group_id)
    return "private"


# 查询积分命令
check_points = on_command("积分", aliases={"查积分", "我的积分", "查分", "余额", "我的余额"}, priority=5, block=True)

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
        f"🏷️ 称号：{title_info['title']} [{title_info['rarity']}]\n"
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


low_income = on_command("低保", aliases={"领取低保", "低保领取"}, priority=5, block=True)


@low_income.handle()
async def handle_low_income(event: MessageEvent):
    user_id = event.get_user_id()
    group_id = _event_group_id(event)
    result = claim_low_income(user_id, group_id)
    record = result["record"]

    if result["status"] == "claimed":
        sync_user_titles(user_id, group_id, record)
        await low_income.finish(
            "（抖开袖中小账）见你囊中不足百，本猫添上 100 积分。\n"
            f"当前积分：{record['current']}｜累计获得：{record['total']}\n"
            "『薄酒也能添暖意，\n"
            "小分暂解一时贫。\n"
            "明朝若又风霜紧，\n"
            "再来账前问本猫。』"
        )

    if result["status"] == "already_claimed":
        await low_income.finish(
            "（合上账本）今日低保已领过，明日再来。\n"
            f"当前积分：{record['current']}\n"
            "『一日一瓢清酒足，莫把小账翻成山。』"
        )

    await low_income.finish(
        "（拨了拨算盘）你账上还不算窘，低保先留给不足百的诗友。\n"
        f"当前积分：{record['current']}\n"
        "『囊中尚有三分月，且让寒窗先得春。』"
    )


# 排行榜命令
ranking = on_command("排行榜", aliases={"排行", "积分排行", "积分榜", "富豪榜"}, priority=5, block=True)

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
        
        rank_text.append(f"{medal} {nickname}：累计 {user['total']} 积分（现有 {user['current']}）")
    
    # 查找当前用户排名
    my_rank = None
    my_points = None
    all_users = get_group_ranking(group_id, 100)
    for i, user in enumerate(all_users):
        if user["user_id"] == user_id:
            my_rank = i + 1
            my_points = user["total"]
            break
    
    my_rank_text = ""
    if my_rank:
        my_rank_text = f"\n📍 你在第{my_rank}名（累计 {my_points} 积分）"

    await ranking.finish(
        f"🏆 李太白给·积分排行榜 🏆\n"
        f"{'='*20}\n"
        f"（展开金榜）诸位一路攒下的总积分，都写在这卷上了。\n"
        f"{'='*20}\n"
        f"{chr(10).join(rank_text)}"
        f"{my_rank_text}\n"
        f"『榜上高低且随它，日日有分自成名。』"
    )

