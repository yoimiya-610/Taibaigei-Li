import unittest

import mybot.bot  # noqa: F401
from mybot.common.practical_tools import (
    PRACTICAL_TOOL_COST,
    atbash_transform,
    bacon_decode,
    bacon_encode,
    base64_decode,
    base64_encode,
    binary_decode,
    binary_encode,
    build_task_prompt,
    caesar_transform,
    morse_decode,
    morse_encode,
    parse_caesar_request,
    parse_keyed_request,
    parse_mode_text,
    parse_morse_request,
    parse_rail_fence_request,
    parse_polish_request,
    rail_fence_decode,
    rail_fence_encode,
    unicode_escape_decode,
    unicode_escape_encode,
    url_decode,
    url_encode,
    vigenere_transform,
)
from mybot.plugins import practical_tools, translate


class PracticalToolsTest(unittest.TestCase):
    def test_help_items_use_practical_category(self):
        practical_texts = {item.text for item in practical_tools.HELP_ITEMS if item.category == "实用功能"}
        translate_texts = {item.text for item in translate.HELP_ITEMS if item.category == "实用功能"}

        self.assertIn(f"/总结 内容 - 提炼要点，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/润色 内容 - 改顺文案，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/解释 内容 - 白话讲解，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/凯撒 加密 3 内容 - 字母移位，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/摩斯 编码 内容 - 摩斯互转，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/Base64 编码 内容 - Base64互转，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/URL编码 编码 内容 - URL互转，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn(f"/栅栏 加密 3 内容 - 栅栏密码，{PRACTICAL_TOOL_COST}积分", practical_texts)
        self.assertIn("/翻译 内容 - 中英互译，10积分", translate_texts)

    def test_polish_parser_accepts_style_prefixes(self):
        text, style = parse_polish_request("正式 请大家今晚八点开会")

        self.assertEqual(text, "请大家今晚八点开会")
        self.assertIn("正式", style)

    def test_polish_parser_defaults_to_natural_style(self):
        text, style = parse_polish_request("这个通知帮我写顺一点")

        self.assertEqual(text, "这个通知帮我写顺一点")
        self.assertIn("自然", style)

    def test_polish_parser_requires_content_after_style_only(self):
        text, style = parse_polish_request("简洁")

        self.assertEqual(text, "")
        self.assertIn("简洁", style)

    def test_summary_prompt_keeps_user_text(self):
        prompt = build_task_prompt("summary", "今天部署失败，因为 token 过期。")

        self.assertIn("今天部署失败", prompt)
        self.assertIn("3 到 6 条关键要点", prompt)

    def test_explain_prompt_keeps_user_text(self):
        prompt = build_task_prompt("explain", "HTTP 502 Bad Gateway")

        self.assertIn("HTTP 502 Bad Gateway", prompt)
        self.assertIn("排查方向", prompt)

    def test_caesar_parser_accepts_mode_shift_and_text(self):
        mode, shift, text = parse_caesar_request("解密 3 khoor zruog")

        self.assertEqual(mode, "decode")
        self.assertEqual(shift, 3)
        self.assertEqual(text, "khoor zruog")

    def test_caesar_transform_keeps_non_letters(self):
        encoded = caesar_transform("Hello, World! 123", 3)

        self.assertEqual(encoded, "Khoor, Zruog! 123")
        self.assertEqual(caesar_transform(encoded, 3, decode=True), "Hello, World! 123")

    def test_morse_parser_accepts_decode_mode(self):
        mode, text = parse_morse_request("解码 ... --- ...")

        self.assertEqual(mode, "decode")
        self.assertEqual(text, "... --- ...")

    def test_morse_round_trip(self):
        encoded, unsupported = morse_encode("SOS 2026")
        decoded, unknown = morse_decode(encoded)

        self.assertEqual(encoded, "... --- ... / ..--- ----- ..--- -....")
        self.assertEqual(unsupported, [])
        self.assertEqual(decoded, "SOS 2026")
        self.assertEqual(unknown, [])

    def test_morse_encode_reports_unsupported_chars(self):
        encoded, unsupported = morse_encode("猫A")

        self.assertEqual(encoded, ".-")
        self.assertEqual(unsupported, ["猫"])

    def test_rail_fence_round_trip(self):
        mode, rails, text = parse_rail_fence_request("加密 3 WEAREDISCOVEREDFLEEATONCE")
        encoded = rail_fence_encode(text, rails)

        self.assertEqual(mode, "encode")
        self.assertEqual(encoded, "WECRLTEERDSOEEFEAOCAIVDEN")
        self.assertEqual(rail_fence_decode(encoded, rails), text)

    def test_vigenere_round_trip(self):
        mode, key, text = parse_keyed_request("加密 lemon attackatdawn")
        encoded, valid_key = vigenere_transform(text, key)
        decoded, _ = vigenere_transform(encoded, key, decode=True)

        self.assertEqual(mode, "encode")
        self.assertTrue(valid_key)
        self.assertEqual(encoded, "lxfopvefrnhr")
        self.assertEqual(decoded, text)

    def test_bacon_round_trip(self):
        encoded, unsupported = bacon_encode("ABC")
        decoded, unknown = bacon_decode(encoded)

        self.assertEqual(encoded, "AAAAA AAAAB AAABA")
        self.assertEqual(unsupported, [])
        self.assertEqual(decoded, "ABC")
        self.assertEqual(unknown, [])

    def test_rot13_uses_caesar_thirteen(self):
        self.assertEqual(caesar_transform("Hello", 13), "Uryyb")
        self.assertEqual(caesar_transform("Uryyb", 13), "Hello")

    def test_base64_round_trip(self):
        encoded = base64_encode("你好, bot")
        decoded, ok = base64_decode(encoded)

        self.assertTrue(ok)
        self.assertEqual(decoded, "你好, bot")

    def test_url_round_trip(self):
        encoded = url_encode("你好 bot")

        self.assertEqual(encoded, "%E4%BD%A0%E5%A5%BD%20bot")
        self.assertEqual(url_decode(encoded), "你好 bot")

    def test_unicode_escape_round_trip(self):
        encoded = unicode_escape_encode("你好")
        decoded, ok = unicode_escape_decode(encoded)

        self.assertEqual(encoded, "\\u4f60\\u597d")
        self.assertTrue(ok)
        self.assertEqual(decoded, "你好")

    def test_atbash_transform(self):
        self.assertEqual(atbash_transform("Abc Z!"), "Zyx A!")

    def test_binary_round_trip(self):
        encoded = binary_encode("Hi")
        decoded, invalid = binary_decode(encoded)

        self.assertEqual(encoded, "01001000 01101001")
        self.assertEqual(decoded, "Hi")
        self.assertEqual(invalid, [])

    def test_mode_parser_defaults_to_encode(self):
        self.assertEqual(parse_mode_text("编码 hello"), ("encode", "hello"))
        self.assertEqual(parse_mode_text("hello"), ("encode", "hello"))

    def test_crypto_usage_is_command_specific(self):
        reverse_usage = practical_tools.render_crypto_usage("反转")
        base64_usage = practical_tools.render_crypto_usage("Base64")

        self.assertIn("功能：把整段文本倒序排列。", reverse_usage)
        self.assertIn("用法：/反转 内容", reverse_usage)
        self.assertIn("功能：文本与 Base64 编码互相转换", base64_usage)
        self.assertIn("用法：/Base64 编码 内容", base64_usage)


if __name__ == "__main__":
    unittest.main()
