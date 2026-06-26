import random
import asyncio
import time
from nonebot import on_command, on_message, get_bot
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent
from nonebot.rule import Rule
from plugins.points import add_points
from common.ai_client import is_configured, prompt_completion
from common.feature_flags import is_feature_enabled
from common.help_registry import HelpItem
from common.logger import get_plugin_logger
from common.user_utils import get_nickname


logger = get_plugin_logger(__name__)

HELP_ITEMS = (
    HelpItem("诗词文艺", "/飞花令 - 开始飞花令", 80),
)
COMMAND_ALIASES = (
    "飞花令", "开始飞花令",
    "结束飞花令", "停止飞花令", "飞花令结束",
    "飞花令状态", "诗词状态",
)

# 存储进行中的飞花令 {group_id: {"keyword": str, "used": [], "scores": {}, "last_time": float}}
active_games = {}

# 超时时间（秒）
TIMEOUT_SECONDS = 30

# 关键字列表
KEYWORDS = ["春", "花", "月", "风", "雨", "云", "山", "水", "酒", "梦", 
            "心", "情", "夜", "天", "日", "雪", "柳", "红", "绿", "愁",
            "秋", "冬", "江", "海", "星", "霜", "露", "烟", "泪", "人"]

# 开局文案
START_MESSAGES = [
    "（抚须）诸位诸位，今日本猫雅兴大发，来一场飞花令如何？",
    "（推墨镜）以诗会友，以词传情~ 谁敢与本猫一较高下？",
    "（晃酒壶）酒过三巡，诗兴大起！来来来，飞花令走起~",
    "（甩袖）李白斗酒诗百篇，本猫今日也来凑个热闘！",
]

# 答对文案
CORRECT_MESSAGES = [
    "（抚须）妙哉妙哉！腹有诗书气自华！",
    "（鼓掌）好诗好诗！本猫都要对你刮目相看了~",
    "（举杯）此句甚妙，当浮一大白！",
    "（点头）不错不错，看来是个读过书的~",
    "（竖大拇指）有才华！要不要考虑做本猫的诗友？",
    "（抛媚眼）才华横溢，本猫都有点心动了~",
    "（拍手）妙极妙极！诗仙见了都要点赞！",
    "（推墨镜）可以可以，这文化水平，本猫认可~",
]

# 答错文案 - 不是真诗句
WRONG_MESSAGES = [
    "（摇头）这...阁下是自己编的吧？本猫读书虽少，也看得出来~",
    "（扶额）此句闻所未闻，怕不是阁下梦中所得？",
    "（叹气）虽然本猫欣赏你的创造力，但这不是真诗啊~",
    "（摇扇子）编诗的本事不错，但飞花令要用真诗句哦~",
    "（推墨镜）本猫上知天文下知地理，就是不知道这句出自哪里...",
]

# 重复诗句文案
REPEAT_MESSAGES = [
    "（敲你头）这句已经有人说过了！换一句~",
    "（摇头）此句已出，不可重复，阁下另请高明~",
    "（扇扇子）英雄所见略同，但这句被用过了~",
    "（叹气）晚了一步，此句已被人捷足先登~",
]

# 超时结束文案
TIMEOUT_MESSAGES = [
    "（打哈欠）30秒没人接了...看来诸位才尽了？",
    "（收起酒壶）冷场了冷场了，本猫宣布飞花令结束~",
    "（叹气）无人应答，本猫只好收摊了...",
    "（伸懒腰）30秒的沉默...本猫就当你们认输了~",
]

# 无人得分结束文案
NO_SCORE_MESSAGES = [
    "（叹气）竟无人得分...诸位是不是都去读理科了？",
    "（摇头）一首诗都没对上，本猫很失望啊...",
    "（喝酒）罢了罢了，没人陪本猫玩，自己喝闷酒去了~",
]

async def verify_poetry(text: str, keyword: str) -> dict:
    """使用AI验证是否为真实诗句且包含关键字，并返回出处"""
    if keyword not in text:
        return {"valid": False, "reason": "not_contain"}

    if not is_configured():
        return {"valid": True, "source": "（出处待考）", "reason": "ok"}
    
    prompt = f"""判断以下内容是否是真实存在的中国古诗词名句（包括唐诗、宋词、元曲、古文名句等）。

内容：{text}
要求包含的字：{keyword}

请严格判断，如果是真实的古诗词：
1. 回答"是"
2. 给出出处（作者和作品名，如：李白《静夜思》）

如果不是真实的古诗词，或者是用户自己编的，回答"否"。

格式：
是/否
出处（如果是真诗的话）"""
    
    answer = await prompt_completion(
        prompt,
        max_tokens=100,
        temperature=0.1,
        timeout=15,
    )
    if not answer:
        # API失败时宽松处理，假设是真的
        return {"valid": True, "source": "（出处待考）", "reason": "ok"}

    lines = answer.split("\n")
    is_valid = "是" in lines[0]

    source = ""
    if is_valid and len(lines) > 1:
        source = lines[1].strip()

    return {"valid": is_valid, "source": source, "reason": "invalid" if not is_valid else "ok"}

async def check_timeout(group_id: str):
    """检查超时，30秒无人作答自动结束"""
    await asyncio.sleep(TIMEOUT_SECONDS)
    
    if group_id not in active_games:
        return
    
    game = active_games[group_id]
    
    # 检查是否超时（最后一次作答时间距今超过30秒）
    if time.time() - game["last_time"] >= TIMEOUT_SECONDS:
        await end_game_timeout(group_id)

async def end_game_timeout(group_id: str):
    """超时结束游戏"""
    if group_id not in active_games:
        return
    
    game = active_games[group_id]
    scores = game["scores"]
    keyword = game["keyword"]
    used_count = len(game["used"])
    
    del active_games[group_id]
    
    try:
        bot = get_bot()
    except Exception as exc:
        logger.warning(f"飞花令超时结束获取 bot 失败 group_id={group_id}: {exc}")
        return
    
    timeout_msg = random.choice(TIMEOUT_MESSAGES)
    
    if not scores:
        end_msg = random.choice(NO_SCORE_MESSAGES)
        try:
            await bot.send_group_msg(
                group_id=int(group_id),
                message=f"🎋 飞花令结束 🎋\n"
                        f"{'='*20}\n"
                        f"{timeout_msg}\n"
                        f"{'='*20}\n"
                        f"关键字：「{keyword}」\n"
                        f"收集诗句：0 句\n"
                        f"{'='*20}\n"
                        f"{end_msg}\n"
                        f"{'='*20}\n"
                        f"『飞花令起无人应，\n本猫独自空悲鸣。\n诗词歌赋今何在，\n都去刷短视频了~』"
            )
        except Exception as exc:
            logger.exception(f"发送飞花令无人得分结束消息失败 group_id={group_id}: {exc}")
        return
    
    # 排行榜
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    
    rank_text = []
    for i, (user_id, data) in enumerate(sorted_scores[:10]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        rank_text.append(f"{medal} {data['nickname']}：{data['score']}分（{data['count']}句）")
    
    # 冠军
    champion = sorted_scores[0][1]
    champion_name = champion["nickname"]
    champion_score = champion["score"]
    champion_count = champion["count"]
    
    try:
        await bot.send_group_msg(
            group_id=int(group_id),
            message=f"🎋 飞花令结束 🎋\n"
                    f"{'='*20}\n"
                    f"{timeout_msg}\n"
                    f"{'='*20}\n"
                    f"关键字：「{keyword}」\n"
                    f"共收集 {used_count} 句诗词\n"
                    f"{'='*20}\n"
                    f"🏆 今日诗魁：{champion_name}\n"
                    f"（{champion_count}句，{champion_score}分）\n"
                    f"{'='*20}\n"
                    f"📊 排行榜：\n"
                    f"{chr(10).join(rank_text)}\n"
                    f"{'='*20}\n"
                    f"『飞花令罢曲终散，\n{champion_name}今日最风光。\n腹有诗书气自华，\n改日再来论短长~』"
        )
    except Exception as exc:
        logger.exception(f"发送飞花令结束消息失败 group_id={group_id}: {exc}")

# 开始飞花令
start_poetry = on_command("飞花令", aliases={"开始飞花令"}, priority=5, block=True)

@start_poetry.handle()
async def handle_start_poetry(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await start_poetry.finish("（摇头）飞花令要在群里才热闹嘛~")
    
    group_id = str(event.group_id)
    
    user_id = event.get_user_id()
    nickname = await get_nickname(bot, user_id, context="飞花令开启")
    
    # 检查是否已有游戏
    if group_id in active_games:
        game = active_games[group_id]
        await start_poetry.finish(
            f"（敲桌子）飞花令正在进行中！\n"
            f"{'='*20}\n"
            f"当前关键字：「{game['keyword']}」\n"
            f"已收集：{len(game['used'])} 句\n"
            f"{'='*20}\n"
            f"直接发送含「{game['keyword']}」的诗句~\n"
            f"/结束飞花令 - 手动结束"
        )
    
    # 随机选择关键字
    keyword = random.choice(KEYWORDS)
    start_msg = random.choice(START_MESSAGES)
    
    # 创建游戏
    active_games[group_id] = {
        "keyword": keyword,
        "used": [],
        "scores": {},
        "starter": nickname,
        "last_time": time.time()
    }
    
    # 启动超时检测
    asyncio.create_task(check_timeout(group_id))
    
    await start_poetry.finish(
        f"🎋 李太白给·飞花令 🎋\n"
        f"{'='*20}\n"
        f"{start_msg}\n"
        f"{'='*20}\n"
        f"📢 {nickname} 开启了飞花令！\n"
        f"{'='*20}\n"
        f"今日关键字：「{keyword}」\n"
        f"{'='*20}\n"
        f"规则：\n"
        f"• 发送含「{keyword}」字的古诗词名句\n"
        f"• 必须是真实存在的诗句\n"
        f"• 每句 +15 积分\n"
        f"• 诗句不能重复使用\n"
        f"• 30秒无人作答自动结束\n"
        f"{'='*20}\n"
        f"直接发送诗句即可！\n"
        f"/结束飞花令 - 手动结束\n"
        f"{'='*20}\n"
        f"『飞花令起诗意浓，\n才子佳人齐相逢。\n一字入诗见功底，\n且看今日谁称雄~』"
    )

# 结束飞花令
end_poetry = on_command("结束飞花令", aliases={"停止飞花令", "飞花令结束"}, priority=5, block=True)

@end_poetry.handle()
async def handle_end_poetry(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await end_poetry.finish("（摇头）要在群里操作哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_games:
        await end_poetry.finish("（摊手）当前没有飞花令游戏！输入 /飞花令 开始~")
    
    game = active_games[group_id]
    scores = game["scores"]
    keyword = game["keyword"]
    used_count = len(game["used"])
    
    del active_games[group_id]
    
    if not scores:
        end_msg = random.choice(NO_SCORE_MESSAGES)
        await end_poetry.finish(
            f"🎋 飞花令结束 🎋\n"
            f"{'='*20}\n"
            f"关键字：「{keyword}」\n"
            f"收集诗句：0 句\n"
            f"{'='*20}\n"
            f"{end_msg}\n"
            f"{'='*20}\n"
            f"『飞花令起无人应，\n本猫独自空悲鸣。\n诗词歌赋今何在，\n都去刷短视频了~』"
        )
    
    # 排行榜
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    
    rank_text = []
    for i, (user_id, data) in enumerate(sorted_scores[:10]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        rank_text.append(f"{medal} {data['nickname']}：{data['score']}分（{data['count']}句）")
    
    # 冠军特别表扬
    champion = sorted_scores[0][1]
    champion_name = champion["nickname"]
    champion_score = champion["score"]
    champion_count = champion["count"]
    
    await end_poetry.finish(
        f"🎋 飞花令结束 🎋\n"
        f"{'='*20}\n"
        f"关键字：「{keyword}」\n"
        f"共收集 {used_count} 句诗词\n"
        f"{'='*20}\n"
        f"🏆 今日诗魁：{champion_name}\n"
        f"（{champion_count}句，{champion_score}分）\n"
        f"{'='*20}\n"
        f"📊 排行榜：\n"
        f"{chr(10).join(rank_text)}\n"
        f"{'='*20}\n"
        f"『飞花令罢曲终散，\n{champion_name}今日最风光。\n腹有诗书气自华，\n改日再来论短长~』"
    )

# 监听诗句
def poetry_answer_rule(event: MessageEvent) -> bool:
    """检查是否是飞花令回答"""
    if not is_feature_enabled("poetry_game"):
        return False

    if not isinstance(event, GroupMessageEvent):
        return False
    group_id = str(event.group_id)
    if group_id not in active_games:
        return False
    msg = event.get_plaintext().strip()
    # 排除命令
    if msg.startswith("/"):
        return False
    # 太短的不处理
    if len(msg) < 3:
        return False
    # 检查是否包含关键字
    keyword = active_games[group_id]["keyword"]
    if keyword not in msg:
        return False
    return True

poetry_matcher = on_message(rule=Rule(poetry_answer_rule), priority=6, block=False)

@poetry_matcher.handle()
async def handle_poetry(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return
    
    group_id = str(event.group_id)
    user_id = event.get_user_id()
    
    if group_id not in active_games:
        return
    
    game = active_games[group_id]
    msg = event.get_plaintext().strip()
    keyword = game["keyword"]
    
    # 检查是否重复
    if msg in game["used"]:
        repeat_msg = random.choice(REPEAT_MESSAGES)
        await poetry_matcher.finish(repeat_msg)
    
    # AI验证
    verify_result = await verify_poetry(msg, keyword)
    
    if not verify_result["valid"]:
        wrong_msg = random.choice(WRONG_MESSAGES)
        await poetry_matcher.finish(wrong_msg)
    
    nickname = await get_nickname(bot, user_id, context="飞花令作答")
    
    # 记录诗句
    game["used"].append(msg)
    
    # 更新最后作答时间
    game["last_time"] = time.time()
    
    # 启动新的超时检测
    asyncio.create_task(check_timeout(group_id))
    
    # 记录分数
    if user_id not in game["scores"]:
        game["scores"][user_id] = {"nickname": nickname, "score": 0, "count": 0}
    
    game["scores"][user_id]["score"] += 15
    game["scores"][user_id]["count"] += 1
    
    # 奖励积分
    add_points(user_id, group_id, 15)
    
    correct_msg = random.choice(CORRECT_MESSAGES)
    current_score = game["scores"][user_id]["score"]
    current_count = game["scores"][user_id]["count"]
    source = verify_result.get("source", "")
    
    source_text = f"\n📖 {source}" if source else ""
    
    await poetry_matcher.finish(
        f"✅ {nickname} +15分！{source_text}\n"
        f"{correct_msg}\n"
        f"当前：{current_count}句 / {current_score}分\n"
        f"⏱️ 30秒内继续接龙~"
    )

# 查看当前飞花令状态
check_poetry = on_command("飞花令状态", aliases={"诗词状态"}, priority=5, block=True)

@check_poetry.handle()
async def handle_check(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await check_poetry.finish("（摇头）要在群里查看哦~")
    
    group_id = str(event.group_id)
    
    if group_id not in active_games:
        await check_poetry.finish("（摊手）当前没有飞花令游戏！输入 /飞花令 开始~")
    
    game = active_games[group_id]
    keyword = game["keyword"]
    used_count = len(game["used"])
    scores = game["scores"]
    remaining = max(0, int(TIMEOUT_SECONDS - (time.time() - game["last_time"])))
    
    if not scores:
        await check_poetry.finish(
            f"🎋 飞花令进行中 🎋\n"
            f"{'='*20}\n"
            f"关键字：「{keyword}」\n"
            f"已收集：{used_count} 句\n"
            f"⏱️ 剩余时间：约{remaining}秒\n"
            f"{'='*20}\n"
            f"暂无人得分，快来抢答！"
        )
    
    # 当前排名
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    rank_text = []
    for i, (uid, data) in enumerate(sorted_scores[:5]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        rank_text.append(f"{medal} {data['nickname']}：{data['score']}分")
    
    await check_poetry.finish(
        f"🎋 飞花令进行中 🎋\n"
        f"{'='*20}\n"
        f"关键字：「{keyword}」\n"
        f"已收集：{used_count} 句\n"
        f"⏱️ 剩余时间：约{remaining}秒\n"
        f"{'='*20}\n"
        f"当前排名：\n"
        f"{chr(10).join(rank_text)}\n"
        f"{'='*20}\n"
        f"继续发送含「{keyword}」的诗句~"
    )

