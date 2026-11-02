from pathlib import Path
import unittest

import mybot.bot  # noqa: F401
from mybot.common.persona import (
    ENDING_POEM_REQUIREMENT,
    GENERATION_FAILURE_MESSAGES,
    PERSONA_IDENTITY,
    PERSONA_SECURITY,
)
from mybot.common.practical_tools import TASKS
from mybot.plugins import ai_chat, fun, love, poem, premium_chat, riddle, roast_target, translate
from mybot.plugins._gift.copy import DRINK_SYSTEM_PROMPT


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PersonaConsistencyTest(unittest.TestCase):
    def test_user_voice_prompts_share_one_identity_baseline(self):
        prompts = (
            ai_chat.SYSTEM_PROMPT,
            ai_chat.CHARM_NOTICE_SYSTEM_PROMPT,
            fun.SYSTEM_PROMPT,
            love.SYSTEM_PROMPT,
            poem.SYSTEM_PROMPT,
            roast_target.SYSTEM_PROMPT,
            DRINK_SYSTEM_PROMPT,
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt[:40]):
                self.assertTrue(prompt.startswith(PERSONA_IDENTITY))
                self.assertIn(PERSONA_SECURITY, prompt)
                self.assertIn("李太白给", prompt)
                self.assertIn("耄耋", prompt)
                self.assertIn("本猫", prompt)

    def test_task_only_and_pro_prompts_keep_identity_without_forcing_poem(self):
        prompts = [
            translate.TRANSLATION_SYSTEM_PROMPT,
            riddle.RIDDLE_SYSTEM_PROMPT,
            love.ACROSTIC_SYSTEM_PROMPT,
            *(task.system_prompt for task in TASKS.values()),
            *(tier["system"] for tier in premium_chat.TIERS.values()),
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt[:40]):
                self.assertTrue(prompt.startswith(PERSONA_IDENTITY))
                self.assertIn(PERSONA_SECURITY, prompt)
                self.assertNotIn(ENDING_POEM_REQUIREMENT, prompt)

    def test_repeated_generation_failures_use_role_safe_shared_copy(self):
        self.assertIs(poem.ERROR_MESSAGES, GENERATION_FAILURE_MESSAGES)
        self.assertIs(love.ERROR_MESSAGES, GENERATION_FAILURE_MESSAGES)
        self.assertIs(fun.ERROR_MESSAGES, GENERATION_FAILURE_MESSAGES)
        self.assertIs(riddle.ERROR_MESSAGES, GENERATION_FAILURE_MESSAGES)
        for message in (*GENERATION_FAILURE_MESSAGES, *roast_target.ERROR_MESSAGES):
            with self.subTest(message=message[:30]):
                self.assertIn("本猫", message)
                self.assertNotIn("API", message)
                self.assertNotIn("模型", message)
                poem_text = message.split("『", 1)[1].rsplit("』", 1)[0]
                self.assertEqual(len(poem_text.splitlines()), 4)

    def test_plugin_prompts_do_not_redefine_the_character(self):
        files = (
            "plugins/ai_chat.py",
            "plugins/fun.py",
            "plugins/love.py",
            "plugins/poem.py",
            "plugins/roast_target.py",
        )
        banned = ("现代吟游诗人", "花花公子猫", "但实际上是个花花公子", "耄耋本猫")
        for relative_path in files:
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            for phrase in banned:
                with self.subTest(file=relative_path, phrase=phrase):
                    self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
