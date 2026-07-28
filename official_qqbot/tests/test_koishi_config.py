import json
import os
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOISHI_DIR = os.path.join(ROOT, "koishi-bridge")


class KoishiConfigTests(unittest.TestCase):
    def test_sqlite_database_dependency_is_declared(self):
        with open(os.path.join(KOISHI_DIR, "package.json"), "r", encoding="utf-8") as f:
            package = json.load(f)

        self.assertIn("@koishijs/plugin-database-sqlite", package["dependencies"])

    def test_database_plugin_loads_before_qq_adapter(self):
        env = {
            **os.environ,
            "QQ_APP_ID": "test-app-id",
            "QQ_APP_SECRET": "test-app-secret",
        }
        result = subprocess.run(
            [
                "node",
                "-e",
                "const c=require('./koishi.config.js'); console.log(JSON.stringify(Object.keys(c.plugins)))",
            ],
            cwd=KOISHI_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        keys = json.loads(result.stdout)

        self.assertLess(keys.index("database-sqlite"), keys.index("adapter-qq-crack"))

    def test_config_provides_webcrypto_for_webhook_signature(self):
        env = {
            **os.environ,
            "QQ_APP_ID": "test-app-id",
            "QQ_APP_SECRET": "test-app-secret",
        }
        script = """
Object.defineProperty(globalThis, 'crypto', {
  value: undefined,
  configurable: true,
  writable: true,
})
require('./koishi.config.js')
console.log(Boolean(globalThis.crypto && globalThis.crypto.subtle))
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "true")

    def test_qq_adapter_defaults_to_websocket_for_full_group_events(self):
        env = {
            **os.environ,
            "QQ_APP_ID": "test-app-id",
            "QQ_APP_SECRET": "test-app-secret",
        }
        env.pop("QQ_ADAPTER_PROTOCOL", None)
        result = subprocess.run(
            [
                "node",
                "-e",
                "const c=require('./koishi.config.js'); console.log(c.plugins['adapter-qq-crack'].protocol)",
            ],
            cwd=KOISHI_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "websocket")

    def test_qq_adapter_protocol_can_be_overridden(self):
        env = {
            **os.environ,
            "QQ_APP_ID": "test-app-id",
            "QQ_APP_SECRET": "test-app-secret",
            "QQ_ADAPTER_PROTOCOL": "webhook",
        }
        result = subprocess.run(
            [
                "node",
                "-e",
                "const c=require('./koishi.config.js'); console.log(c.plugins['adapter-qq-crack'].protocol)",
            ],
            cwd=KOISHI_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "webhook")


if __name__ == "__main__":
    unittest.main()
