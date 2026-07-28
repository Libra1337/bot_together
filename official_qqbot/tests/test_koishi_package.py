import json
import os
import unittest


class KoishiPackageTests(unittest.TestCase):
    def test_start_script_passes_config_as_positional_file(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        package_path = os.path.join(root, "koishi-bridge", "package.json")
        with open(package_path, "r", encoding="utf-8") as f:
            package = json.load(f)

        self.assertEqual(package["scripts"]["start"], "koishi start koishi.config.js")


if __name__ == "__main__":
    unittest.main()
