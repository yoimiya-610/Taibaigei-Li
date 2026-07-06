import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mybot.common import feature_flags


class YoimiyaRenameTest(unittest.TestCase):
    def test_legacy_feature_key_still_controls_renamed_plugin(self):
        with TemporaryDirectory() as tmp_dir:
            flags_path = Path(tmp_dir) / "feature_flags.json"
            flags_path.write_text(json.dumps({"features": {"youyimiya": False}}), encoding="utf-8")

            with patch.object(feature_flags, "FEATURE_FLAGS_FILE", flags_path):
                self.assertFalse(feature_flags.is_feature_enabled("yoimiya"))
                self.assertEqual(feature_flags.resolve_feature("youyimiya"), "yoimiya")

                feature_flags.set_feature_enabled("youyimiya", True)
                flags = json.loads(flags_path.read_text(encoding="utf-8"))

        self.assertIs(flags["features"]["yoimiya"], True)

    def test_yoimiya_triggers_do_not_duplicate_blacklist(self):
        from mybot.plugins import blacklist, yoimiya

        self.assertTrue(yoimiya.TRIGGER_WORDS)
        self.assertTrue(set(yoimiya.TRIGGER_WORDS).isdisjoint(blacklist.BLACKLIST_WORDS))


if __name__ == "__main__":
    unittest.main()
