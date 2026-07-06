from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyGameInfo:
    feature_key: str
    module_name: str
    display_name: str
    primary_command: str
    help_order: int
    usage: tuple[str, ...]
    summary: str


LEGACY_GAMES: tuple[LegacyGameInfo, ...] = (
    LegacyGameInfo(
        feature_key="legacy_slot",
        module_name="slot",
        display_name="图案转盘",
        primary_command="/图案转盘 金额",
        help_order=20,
        usage=("/图案转盘 金额",),
        summary="转出三个相同图案可获对应倍数奖励，两个樱桃返还1.25倍；单次最多100积分。",
    ),
    LegacyGameInfo(
        feature_key="legacy_dice",
        module_name="dice",
        display_name="点数方块",
        primary_command="/点数方块",
        help_order=30,
        usage=("/点数方块", "/选大 金额", "/选小 金额", "/选三同 金额", "/结算"),
        summary="三枚方块总和11-17为大、4-10为小，猜中大小得1.95倍，猜中三同得34倍；单次最多100积分。",
    ),
    LegacyGameInfo(
        feature_key="legacy_blackjack",
        module_name="blackjack",
        display_name="纸牌挑战",
        primary_command="/纸牌挑战 金额",
        help_order=40,
        usage=("/纸牌挑战 金额", "/要牌", "/停牌", "/弃牌"),
        summary="点数尽量接近21且不可超过，普通胜局得2倍，开局21点得3倍；单次最多100积分。",
    ),
    LegacyGameInfo(
        feature_key="legacy_race",
        module_name="race",
        display_name="赛博竞速",
        primary_command="/赛博竞速",
        help_order=50,
        usage=("/赛博竞速", "/选马 编号 金额", "/开跑", "/取消竞速"),
        summary="选择参赛者后等待开跑，所选参赛者夺冠按奖池折算分账，保底约1.9倍；单次最多100积分。",
    ),
    LegacyGameInfo(
        feature_key="legacy_roulette",
        module_name="roulette",
        display_name="转盘挑战",
        primary_command="/转盘挑战 金额",
        help_order=60,
        usage=("/转盘挑战 金额", "/转盘 金额（单人）", "/加入转盘", "/开始转盘", "/转一轮", "/取消转盘"),
        summary="单人模式通过安全格可得0.15倍奖励；多人模式支持2至6人，最后留在局中的人获得95%积分池；单次最多100积分。",
    ),
)

LEGACY_GAME_ORDER = tuple(game.feature_key for game in LEGACY_GAMES)
LEGACY_GAME_BY_KEY = {game.feature_key: game for game in LEGACY_GAMES}
LEGACY_GAME_BY_MODULE = {game.module_name: game for game in LEGACY_GAMES}
LEGACY_GAME_NAMES = {game.feature_key: game.display_name for game in LEGACY_GAMES}
