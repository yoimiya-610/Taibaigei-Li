from mybot.common.plugin_metadata import declare_plugin

PLUGIN_META = declare_plugin(
    module_name=__name__,
    feature_key="rate_limit",
    name="频率限制",
    default_enabled=True,
    scope="group",
    permission_level=5,
    privacy_level="internal",
    backup_policy="none",
)

from mybot.common.usage_policy import (
    HISTORY_GAME_QUOTA,
    QuotaScope,
    consume_quota,
    quota_records,
)

# 兼容既有测试与运维清理入口；实际键由共享配额策略维护。
game_records = quota_records

# 限制配置
LIMIT_COUNT = 10      # 10次
LIMIT_WINDOW = 300    # 5分钟（秒）

def check_game_limit(user_id: str, group_id: str) -> tuple:
    """
    检查用户是否超过历史小游戏共享限制
    返回 (是否可以玩, 剩余次数或等待秒数)
    """
    decision = consume_quota(
        "legacy_games",
        str(user_id),
        str(group_id),
        HISTORY_GAME_QUOTA,
    )
    if not decision.allowed:
        return (False, decision.wait_seconds)
    remaining = (decision.remaining or {}).get(QuotaScope.USER, 0)
    return (True, remaining)

def get_limit_message(wait_time: int) -> str:
    """返回限制提示文案"""
    minutes = wait_time // 60
    seconds = wait_time % 60
    
    messages = [
        f"（按住你）慢点慢点！5分钟内只能玩10次，还要等{minutes}分{seconds}秒~",
        f"（摇头）玩太多了！歇一歇吧，{minutes}分{seconds}秒后再来~",
        f"（收起道具）文娱也要有节制！{minutes}分{seconds}秒后再来~",
        f"（推墨镜）本猫劝你冷静一下，{minutes}分{seconds}秒后再来~",
    ]
    
    import random
    return random.choice(messages)
