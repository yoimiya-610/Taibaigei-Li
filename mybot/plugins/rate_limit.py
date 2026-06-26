import time
from collections import defaultdict

# 游戏记录 {user_id: [(timestamp1, timestamp2, ...)]}
game_records = defaultdict(list)

# 限制配置
LIMIT_COUNT = 5      # 5次
LIMIT_WINDOW = 600    # 10分钟（秒）

def check_game_limit(user_id: str, group_id: str) -> tuple:
    """
    检查用户是否超过游戏限制
    返回 (是否可以玩, 剩余次数或等待秒数)
    """
    key = f"{group_id}_{user_id}"
    now = time.time()
    
    # 清理过期记录
    game_records[key] = [t for t in game_records[key] if now - t < LIMIT_WINDOW]
    
    # 检查次数
    if len(game_records[key]) >= LIMIT_COUNT:
        # 计算最早记录还要多久过期
        oldest = min(game_records[key])
        wait_time = int(LIMIT_WINDOW - (now - oldest))
        return (False, wait_time)
    
    # 记录本次
    game_records[key].append(now)
    remaining = LIMIT_COUNT - len(game_records[key])
    
    return (True, remaining)

def get_limit_message(wait_time: int) -> str:
    """返回限制提示文案"""
    minutes = wait_time // 60
    seconds = wait_time % 60
    
    messages = [
        f"（按住你）慢点慢点！10分钟内只能玩10次，还要等{minutes}分{seconds}秒~",
        f"（摇头）玩太多了！歇一歇吧，{minutes}分{seconds}秒后再来~",
        f"（收起道具）文娱也要有节制！{minutes}分{seconds}秒后再来~",
        f"（推墨镜）本猫劝你冷静一下，{minutes}分{seconds}秒后再来~",
    ]
    
    import random
    return random.choice(messages)
