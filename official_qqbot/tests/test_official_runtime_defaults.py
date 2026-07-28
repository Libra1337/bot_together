import importlib
import os
import unittest

import yaml


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OfficialRuntimeDefaultsTests(unittest.TestCase):
    def test_config_defaults_to_official_websocket_without_bridge_listener(self):
        with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.assertIs(config["bot"].get("official_ws_enabled"), True)
        self.assertIs(config["bridge"].get("enabled"), False)

    def test_deploy_env_defaults_to_webhook_bridge_when_https_callback_is_required(self):
        path = os.path.join(ROOT, "deploy", "ubuntu", "koishi-bridge.env.example")
        with open(path, "r", encoding="utf-8") as f:
            env = f.read()

        self.assertIn("QQ_OFFICIAL_WS_ENABLED=0", env)
        self.assertIn("QQ_BRIDGE_ENABLED=1", env)
        self.assertIn("QQ_WEBHOOK_FORWARD_URL=http://127.0.0.1:8765/qq", env)

    def test_bridge_env_can_explicitly_disable_listener(self):
        import bot

        old_value = os.environ.get("QQ_BRIDGE_ENABLED")
        try:
            os.environ["QQ_BRIDGE_ENABLED"] = "0"
            importlib.reload(bot)
            self.assertFalse(bot.BRIDGE_ENABLED)
        finally:
            if old_value is None:
                os.environ.pop("QQ_BRIDGE_ENABLED", None)
            else:
                os.environ["QQ_BRIDGE_ENABLED"] = old_value
            importlib.reload(bot)


if __name__ == "__main__":
    unittest.main()
