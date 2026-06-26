import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from plugins.points import get_points, spend_points
from common.ai_client import prompt_completion
from common.help_registry import HelpItem
from common.user_utils import get_nickname


HELP_ITEMS = (
    HelpItem("社交互动", "/代骂 - 太白代骂，15积分", 40),
)
COMMAND_ALIASES = ("代骂", "帮我骂", "骂ta")


SYSTEM_PROMPT = """你是"李太白给"，一只花花公子猫。自称"本猫"。
要求用文雅、诗意但毒舌的方式骂人，不能用脏话，要有文化底蕴，可以引用典故，最后附带一首讽刺的打油诗。"""

ERROR_MESSAGES = [
    "（扶额）本猫的脑子好像宕机了...改日再骂吧~",
    "（晃酒壶）本猫喝多了，骂不动了...",
]

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
    
    # 检查积分
    points = get_points(user_id, group_id)
    if points["current"] < 15:
        await roast_target.finish(f"（摇头）代骂服务需要15积分，你只有{points['current']}积分~")
    
    # 扣积分
    spend_points(user_id, group_id, 15)
    
    sender_name = await get_nickname(bot, user_id, context="代骂.sender")
    target_name = await get_nickname(bot, target_id, context="代骂.target")
    
    prompt = f"""{sender_name}花钱请你骂{target_name}。

请用文雅但毒舌的方式骂{target_name}：
1. 不能用脏话，要有文化底蕴
2. 可以引用典故或诗词
3. 语气要傲娇，骂完还要补一刀
4. 最后附带一首讽刺的打油诗
5. 不要太过分，点到为止"""

    reply = await call_api(prompt)
    
    if reply:
        await roast_target.finish(
            f"🎭 李太白给·代骂服务 🎭\n"
            f"{'='*20}\n"
            f"（推墨镜）{sender_name}花钱请本猫教训{target_name}~\n"
            f"{'='*20}\n"
            f"{reply}\n"
            f"{'='*20}\n"
            f"（消耗 15 积分）"
        )
    else:
        # 退还积分
        from plugins.points import add_points
        add_points(user_id, group_id, 15)
        await roast_target.finish(random.choice(ERROR_MESSAGES))

