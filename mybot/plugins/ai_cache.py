import random
import time
import hashlib
from collections import defaultdict

# 近期生成记录 {命令类型: [(内容摘要, 时间戳), ...]}
recent_cache = defaultdict(list)

# 缓存配置
CACHE_SIZE = 20        # 每个命令记录最近20条
CACHE_EXPIRE = 3600    # 1小时过期

# 随机元素库
RANDOM_STYLES = ["幽默风趣", "文艺诗意", "调侃戏谑", "深情款款", "玩世不恭", "傲娇毒舌"]
RANDOM_MOODS = ["开心", "忧郁", "慵懒", "兴奋", "无聊", "微醺"]
RANDOM_SEASONS = ["春日", "夏夜", "秋风", "冬雪"]
RANDOM_TIMES = ["清晨", "午后", "黄昏", "深夜", "凌晨"]

def get_content_hash(content: str) -> str:
    """获取内容摘要（前50字的hash）"""
    return hashlib.md5(content[:50].encode()).hexdigest()[:8]

def is_duplicate(cmd_type: str, content: str) -> bool:
    """检查内容是否与近期重复"""
    now = time.time()
    content_hash = get_content_hash(content)
    
    # 清理过期记录
    recent_cache[cmd_type] = [
        (h, t) for h, t in recent_cache[cmd_type] 
        if now - t < CACHE_EXPIRE
    ]
    
    # 检查是否重复
    for h, _ in recent_cache[cmd_type]:
        if h == content_hash:
            return True
    return False

def add_to_cache(cmd_type: str, content: str):
    """添加到缓存"""
    now = time.time()
    content_hash = get_content_hash(content)
    
    recent_cache[cmd_type].append((content_hash, now))
    
    # 限制大小
    if len(recent_cache[cmd_type]) > CACHE_SIZE:
        recent_cache[cmd_type] = recent_cache[cmd_type][-CACHE_SIZE:]

def get_random_factors() -> dict:
    """获取随机因素，用于prompt"""
    return {
        "seed": random.randint(1, 99999),
        "style": random.choice(RANDOM_STYLES),
        "mood": random.choice(RANDOM_MOODS),
        "season": random.choice(RANDOM_SEASONS),
        "time": random.choice(RANDOM_TIMES),
        "lucky_num": random.randint(1, 100),
        "temperature_hint": random.choice(["热情洋溢", "冷静克制", "随性自然"]),
    }

def build_random_prompt(base_prompt: str, factors: dict = None) -> str:
    """构建带随机因素的prompt"""
    if factors is None:
        factors = get_random_factors()
    
    random_section = f"""
【随机参数 - 用于增加多样性，请根据这些参数调整风格】
- 随机种子：{factors['seed']}
- 风格倾向：{factors['style']}
- 情绪基调：{factors['mood']}
- 季节意象：{factors['season']}
- 时间氛围：{factors['time']}
- 幸运数字：{factors['lucky_num']}
- 表达温度：{factors['temperature_hint']}

请根据以上随机参数，生成与之前不同的内容。
"""
    return base_prompt + random_section
