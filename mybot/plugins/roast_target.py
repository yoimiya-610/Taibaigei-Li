import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from mybot.plugins.points import refund_points, spend_points
from mybot.common.ai_client import prompt_completion
from mybot.common.help_registry import HelpItem
from mybot.common.logger import get_plugin_logger
from mybot.common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("社交互动", "/代骂 - 太白代骂，15积分起", 40),
)
COMMAND_ALIASES = ("代骂", "帮我骂", "骂ta")


SYSTEM_PROMPT = """你是"李太白给"，一只花花公子猫。自称"本猫"。
要求用文雅、诗意但毒舌的方式骂人，不能用脏话，要有文化底蕴，可以引用典故，最后附带一首讽刺的打油诗。"""

ERROR_MESSAGES = [
    "（酒壶轻晃）这一回笔锋未能落成，15 积分已原样归还。\n『墨痕未落风先起，且待来朝再写诗。』",
    "（收起折扇）本猫今日没写成这封檄文，15 积分已送回账上。\n『酒醒重磨三尺墨，明朝再借一身风。』",
]

logger = get_plugin_logger(__name__)

async def call_api(prompt: str) -> str:
    return await prompt_completion(
        prompt,
        system=SYSTEM_PROMPT,
        max_tokens=500,
        temperature=0.9,
    )

# 代骂
roast_target = on_command("代骂", aliases={"帮我骂", "骂ta"}, priority=5, block=True)

@roast_target.handle()
async def handle_roast_target(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        await roast_target.finish("（摇头）代骂要在群里操作~")
    
    user_id = event.get_user_id()
    group_id = str(event.group_id)
    
    # 解析@的人
    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq"))
            break
    
    if not target_id:
        await roast_target.finish(
            f"🎭 代骂服务 🎭\n"
            f"{'='*20}\n"
            f"用法：/代骂 @某人\n"
            f"消耗：15积分\n"
            f"{'='*20}\n"
            f"（推墨镜）让本猫替你文雅地教训ta~"
        )
    
    if target_id == user_id:
        await roast_target.finish("（扶额）花钱骂自己？你是受虐狂吗...")
    
    # spend_points performs the balance check and deduction under one storage lock.
    if not spend_points(user_id, group_id, 15):
        await roast_target.finish(
            "（翻账本）这场笔锋需 15 积分，阁下账上余墨不足。\n"
            "『囊中先攒三分墨，来日方书一纸锋。』"
        )

    try:
        sender_name = await get_nickname(bot, user_id, context="代骂.sender")
        target_name = await get_nickname(bot, target_id, context="代骂.target")

        prompt = f"""{sender_name}请本猫替他教训{target_name}。

请用文雅但毒舌的方式骂{target_name}：
1. 不能用脏话，要有文化底蕴
2. 可以引用典故或诗词
3. 语气要傲娇，骂完还要补一刀
4. 最后附带一首讽刺的打油诗
5. 不要太过分，点到为止"""

        reply = await call_api(prompt)
        if not reply:
            raise RuntimeError("empty_roast_reply")
    except Exception as exc:
        logger.exception(f"代骂生成失败 user_id={user_id} group_id={group_id}: {exc}")
        refund_points(user_id, group_id, 15)
        await roast_target.finish(random.choice(ERROR_MESSAGES))

    await roast_target.finish(
        f"🎭 李太白给·代骂 🎭\n"
        f"{'='*20}\n"
        f"（推墨镜）{sender_name}请本猫替他教训{target_name}~\n"
        f"{'='*20}\n"
        f"{reply}\n"
        f"{'='*20}\n"
        f"（本次收下 15 积分）"
    )

