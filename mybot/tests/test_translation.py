import unittest

from mybot.common.translation import (
    TRANSLATION_COST,
    detect_default_pair,
    parse_translation_request,
    supported_language_help,
)


class TranslationTest(unittest.TestCase):
    def test_default_translation_detects_chinese_to_english(self):
        request = parse_translation_request("模型调用超时，请稍后重试")

        self.assertEqual(request.source_language, "中文")
        self.assertEqual(request.target_language, "英文")
        self.assertEqual(request.text, "模型调用超时，请稍后重试")
        self.assertFalse(request.explicit_pair)

    def test_default_translation_detects_english_to_chinese(self):
        self.assertEqual(detect_default_pair("Token expired during deployment"), ("英文", "中文"))

    def test_explicit_language_pair_parser(self):
        request = parse_translation_request("日译中 お疲れ様でした")

        self.assertEqual(request.source_language, "日文")
        self.assertEqual(request.target_language, "中文")
        self.assertEqual(request.text, "お疲れ様でした")
        self.assertTrue(request.explicit_pair)

    def test_explicit_language_pair_accepts_codes(self):
        request = parse_translation_request("en译zh Kubernetes rollout failed")

        self.assertEqual(request.source_language, "英文")
        self.assertEqual(request.target_language, "中文")
        self.assertEqual(request.text, "Kubernetes rollout failed")

    def test_blank_translation_returns_none_for_usage(self):
        self.assertIsNone(parse_translation_request("   "))

    def test_help_mentions_cost_and_language_pair_usage(self):
        help_text = supported_language_help()

        self.assertIn(f"{TRANSLATION_COST} 积分", help_text)
        self.assertIn("/翻译 a译b 内容", help_text)
        self.assertIn("日译中", help_text)


if __name__ == "__main__":
    unittest.main()
