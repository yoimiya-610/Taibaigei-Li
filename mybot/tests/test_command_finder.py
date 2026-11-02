import unittest
from unittest.mock import patch

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from mybot.common.command_discovery import (
    extract_explicit_command,
    is_registered_explicit_command,
    search_public_commands,
    suggest_public_commands,
)
from mybot.plugins import command_finder


def _group_event(message: str) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 1,
            "user_id": 10001,
            "group_id": 20001,
            "message": [{"type": "text", "data": {"text": message}}],
            "original_message": [
                {"type": "text", "data": {"text": message}}
            ],
            "raw_message": message,
            "font": 0,
            "sender": {
                "user_id": 10001,
                "nickname": "tester",
                "role": "member",
            },
        }
    )


class CommandFinderTest(unittest.TestCase):
    def test_searches_primary_commands_aliases_and_gameplay_copy(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            signin = search_public_commands("签到")
            alias = search_public_commands("查分")
            gameplay = search_public_commands("猜拳")
            typo = search_public_commands("命令全蓝")

        self.assertEqual(signin[0].text, "/签到 - 每日运势签到")
        self.assertEqual(alias[0].text, "/查分")
        self.assertEqual(alias[0].kind, "alias")
        self.assertTrue(any("/对饮猜拳" in result.text for result in gameplay))
        self.assertEqual(typo[0].text, "/命令全览 - 查看全部命令")

    def test_search_only_uses_public_catalog(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            results = search_public_commands("管理员", limit=50)

        rendered = "\n".join(result.text for result in results)
        self.assertNotIn("/管理员", rendered)
        self.assertNotIn("/功能列表", rendered)
        self.assertNotIn("/debug", rendered)

    def test_typo_suggests_the_closest_public_entrance(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            suggestions = suggest_public_commands("运式")

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0], "/运势")

    def test_typo_never_reveals_admin_commands(self):
        with patch("mybot.common.help_registry.is_feature_enabled", return_value=True):
            suggestions = suggest_public_commands(
                "功能列飙",
                limit=50,
                minimum_score=0,
            )

        self.assertNotIn("/功能列表", suggestions)
        self.assertNotIn("/管理员", suggestions)
        self.assertNotIn("/debug", suggestions)

    def test_explicit_command_detection_supports_fullwidth_slash_and_arguments(self):
        self.assertEqual(extract_explicit_command(" ／运式 今日 "), "运式")
        self.assertTrue(is_registered_explicit_command("/签到 今日"))
        self.assertFalse(is_registered_explicit_command("/运式 今日"))
        self.assertIsNone(extract_explicit_command("普通聊天"))
        self.assertIsNone(extract_explicit_command(" / "))

    def test_unknown_rule_only_catches_unregistered_slash_commands_when_enabled(self):
        with patch.object(command_finder, "is_feature_enabled", return_value=True):
            self.assertTrue(
                command_finder._should_suggest_unknown(_group_event("/运式"))
            )
            self.assertFalse(
                command_finder._should_suggest_unknown(_group_event("/运势"))
            )
            self.assertFalse(
                command_finder._should_suggest_unknown(_group_event("普通聊天"))
            )
        with patch.object(command_finder, "is_feature_enabled", return_value=False):
            self.assertFalse(
                command_finder._should_suggest_unknown(_group_event("/运式"))
            )

    def test_unknown_render_truncates_untrusted_command_text(self):
        event = unittest.mock.Mock()
        event.get_user_id.return_value = "10001"
        text = command_finder._render_unknown_command("错" * 100, event)

        self.assertLess(len(text), 300)
        self.assertIn("…", text)

    def test_empty_search_has_role_appropriate_usage(self):
        event = unittest.mock.Mock()
        event.get_user_id.return_value = "10001"
        text = command_finder._render_search("", event)

        self.assertIn("用法：/寻令 关键词", text)
        self.assertIn("例：/寻令 签到", text)
        self.assertNotIn("API", text)


if __name__ == "__main__":
    unittest.main()
