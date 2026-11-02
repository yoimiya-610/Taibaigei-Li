import unittest

from mybot.common.ai_context import (
    AIContextDatabase,
    AIContextRequest,
    AIContextRouter,
)


def _database(
    key: str,
    topic: str,
    content: str,
) -> AIContextDatabase:
    return AIContextDatabase(
        key=key,
        title=f"《{key}》",
        matcher=lambda request: topic in request.message,
        renderer=lambda request: content,
    )


class AIContextRouterTest(unittest.TestCase):
    def test_router_attaches_only_relevant_database(self):
        router = AIContextRouter(
            (
                _database("本事簿", "能力", "公开能力资料"),
                _database("诗词簿", "诗词", "诗词资料"),
            )
        )

        context = router.build_context(AIContextRequest("介绍一下能力"))

        self.assertIn("公开能力资料", context)
        self.assertNotIn("诗词资料", context)

    def test_router_can_attach_multiple_relevant_databases(self):
        router = AIContextRouter(
            (
                _database("甲卷", "共同主题", "甲卷资料"),
                _database("乙卷", "共同主题", "乙卷资料"),
            )
        )

        context = router.build_context(AIContextRequest("请查共同主题"))

        self.assertIn("甲卷资料", context)
        self.assertIn("乙卷资料", context)

    def test_router_returns_empty_context_without_match(self):
        router = AIContextRouter((_database("本事簿", "能力", "公开能力资料"),))

        context = router.build_context(AIContextRequest("帮我生成一首诗歌"))

        self.assertEqual(context, "")

    def test_database_receives_conversation_scope(self):
        database = AIContextDatabase(
            key="scoped",
            title="《作用域资料》",
            matcher=lambda request: request.group_id == "20001",
            renderer=lambda request: f"{request.group_id}:{request.user_id}",
        )
        router = AIContextRouter((database,))

        context = router.build_context(
            AIContextRequest("查询", group_id="20001", user_id="10001")
        )

        self.assertIn("20001:10001", context)

    def test_router_rejects_duplicate_database_keys(self):
        databases = (
            _database("duplicate", "甲", "甲资料"),
            _database("duplicate", "乙", "乙资料"),
        )

        with self.assertRaises(ValueError):
            AIContextRouter(databases)


if __name__ == "__main__":
    unittest.main()
