import json
import tempfile
import unittest
from pathlib import Path

from feature_flags import FeatureFlags


class FeatureFlagsTests(unittest.TestCase):
    def test_missing_state_keeps_builtin_feature_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            flags = FeatureFlags(Path(tmp) / "plugins.json")

            self.assertTrue(flags.enabled("builtin.nfa"))

    def test_state_file_can_disable_builtin_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugins.json"
            path.write_text(
                json.dumps({"plugins": {"builtin.nfa": {"enabled": False}}}),
                encoding="utf-8",
            )
            flags = FeatureFlags(path)

            self.assertFalse(flags.enabled("builtin.nfa"))


if __name__ == "__main__":
    unittest.main()
