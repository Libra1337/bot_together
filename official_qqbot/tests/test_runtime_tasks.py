import unittest

import bot


class RuntimeTaskTests(unittest.TestCase):
    def test_official_ws_can_be_disabled_while_bridge_stays_enabled(self):
        old_ws = bot.run_websocket
        old_token = bot.token_refresh_loop
        old_bridge = bot.run_koishi_bridge_server
        bot.run_websocket = lambda: "ws"
        bot.token_refresh_loop = lambda: "token"
        bot.run_koishi_bridge_server = lambda: "bridge"
        try:
            tasks = bot._build_runtime_tasks(official_ws_enabled=False, bridge_enabled=True)

            self.assertEqual(tasks, ["token", "bridge"])
        finally:
            bot.run_websocket = old_ws
            bot.token_refresh_loop = old_token
            bot.run_koishi_bridge_server = old_bridge

    def test_official_runtime_uses_websocket_without_bridge_by_default(self):
        old_ws = bot.run_websocket
        old_token = bot.token_refresh_loop
        old_bridge = bot.run_koishi_bridge_server
        bot.run_websocket = lambda: "ws"
        bot.token_refresh_loop = lambda: "token"
        bot.run_koishi_bridge_server = lambda: "bridge"
        try:
            tasks = bot._build_runtime_tasks(
                official_ws_enabled=True, bridge_enabled=False
            )

            self.assertEqual(tasks, ["ws", "token"])
        finally:
            bot.run_websocket = old_ws
            bot.token_refresh_loop = old_token
            bot.run_koishi_bridge_server = old_bridge


if __name__ == "__main__":
    unittest.main()
