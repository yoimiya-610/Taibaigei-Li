from dataclasses import dataclass
import re


TRANSLATION_COST = 10
MAX_TRANSLATION_TEXT_LENGTH = 1200


@dataclass(frozen=True)
class TranslationRequest:
    source_language: str
    target_language: str
    text: str
    explicit_pair: bool = False


LANGUAGE_ALIASES = {
    "中": "中文",
    "中文": "中文",
    "汉语": "中文",
    "zh": "中文",
    "cn": "中文",
    "英": "英文",
    "英文": "英文",
    "英语": "英文",
    "en": "英文",
    "日": "日文",
    "日文": "日文",
    "日语": "日文",
    "jp": "日文",
    "ja": "日文",
    "韩": "韩文",
    "韩文": "韩文",
    "韩语": "韩文",
    "kr": "韩文",
    "ko": "韩文",
    "法": "法文",
    "法文": "法文",
    "法语": "法文",
    "fr": "法文",
    "德": "德文",
    "德文": "德文",
    "德语": "德文",
    "de": "德文",
    "西": "西班牙文",
    "西文": "西班牙文",
    "西班牙语": "西班牙文",
    "es": "西班牙文",
    "俄": "俄文",
    "俄文": "俄文",
    "俄语": "俄文",
    "ru": "俄文",
    "葡": "葡萄牙文",
    "葡文": "葡萄牙文",
    "葡萄牙语": "葡萄牙文",
    "pt": "葡萄牙文",
    "意": "意大利文",
    "意文": "意大利文",
    "意大利语": "意大利文",
    "it": "意大利文",
    "阿": "阿拉伯文",
    "阿文": "阿拉伯文",
    "阿拉伯语": "阿拉伯文",
    "ar": "阿拉伯文",
    "泰": "泰文",
    "泰文": "泰文",
    "泰语": "泰文",
    "th": "泰文",
    "越": "越南文",
    "越文": "越南文",
    "越南语": "越南文",
    "vi": "越南文",
}


PAIR_PATTERN = re.compile(r"^([A-Za-z\u4e00-\u9fff]+)\s*译\s*([A-Za-z\u4e00-\u9fff]+)\s+(.+)$", re.DOTALL)


def normalize_language_name(raw: str) -> str | None:
    return LANGUAGE_ALIASES.get(raw.strip().lower())


def detect_default_pair(text: str) -> tuple[str, str]:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in text if char.isascii() and char.isalpha())
    if cjk_count >= latin_count:
        return "中文", "英文"
    return "英文", "中文"


def parse_translation_request(raw_text: str) -> TranslationRequest | None:
    text = raw_text.strip()
    if not text:
        return None

    match = PAIR_PATTERN.match(text)
    if match:
        source = normalize_language_name(match.group(1))
        target = normalize_language_name(match.group(2))
        content = match.group(3).strip()
        if source and target and content:
            return TranslationRequest(source, target, content, explicit_pair=True)

    source, target = detect_default_pair(text)
    return TranslationRequest(source, target, text)


def supported_language_help() -> str:
    examples = (
        "中译英 / 英译中 / 日译中 / 中译日 / 韩译中 / 法译中 / 德译中 / 西译中 / 俄译中 / 葡译中 / 意译中 / 阿译中 / 泰译中 / 越译中"
    )
    return (
        "🌐 李太白给·翻译 🌐\n"
        "======================\n"
        f"/翻译 内容：自动判断中英互译，每次 {TRANSLATION_COST} 积分。\n"
        "/翻译 a译b 内容：指定其他语言方向。\n"
        f"支持写法：{examples}\n"
        "例：/翻译 The deployment failed because the token expired.\n"
        "例：/翻译 日译中 お疲れ様でした\n"
        "======================\n"
        "『一语过江成两岸，原名仍系旧舟边。』"
    )
