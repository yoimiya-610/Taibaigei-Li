import tempfile
import unittest
from pathlib import Path

from mybot.common.json_store import JsonStoreReadError, load_json, mutate_json


class JsonStoreSafetyTest(unittest.TestCase):
    def test_reading_invalid_json_keeps_legacy_default_behavior(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            path.write_text('{"broken":', encoding="utf-8")

            self.assertEqual(load_json(path, {"safe": True}), {"safe": True})
            self.assertEqual(path.read_text(encoding="utf-8"), '{"broken":')

    def test_mutation_never_overwrites_invalid_json_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            original = '{"broken":'
            path.write_text(original, encoding="utf-8")

            with self.assertRaises(JsonStoreReadError):
                mutate_json(path, {}, lambda data: data.update({"lost": True}))

            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
