import unittest

import bot
import control_api.app as app_module
from control_api.app import create_app
from fastapi.testclient import TestClient


class QQWebhookBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_validation_returns_plain_token_and_signature(self):
        result = await bot.handle_qq_webhook_payload(
            {"op": 13, "d": {"event_ts": "1710000000", "plain_token": "plain-token"}},
            app_secret="test-secret-value",
        )

        self.assertEqual(result["plain_token"], "plain-token")
        self.assertEqual(len(result["signature"]), 128)

    async def test_group_dispatch_from_webhook_uses_existing_handler(self):
        calls = []

        async def fake_handle_group_message(data, event_type):
            calls.append((data, event_type))

        old_handle = bot.handle_group_message
        bot.handle_group_message = fake_handle_group_message
        try:
            result = await bot.handle_qq_webhook_payload(
                {
                    "op": 0,
                    "t": bot.GROUP_AT_MESSAGE_CREATE,
                    "d": {
                        "id": "msg-a",
                        "content": "/help",
                        "group_openid": "group-a",
                        "author": {"member_openid": "user-a"},
                    },
                },
                app_secret="test-secret-value",
            )
        finally:
            bot.handle_group_message = old_handle

        self.assertEqual(result, {"status": "success"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0]["id"], "msg-a")
        self.assertEqual(calls[0][1], bot.GROUP_AT_MESSAGE_CREATE)


class ControlApiQQWebhookProxyTests(unittest.TestCase):
    def test_qq_route_forwards_to_internal_bot_listener(self):
        captured = {}

        async def fake_forward(body, headers, forward_url):
            captured["body"] = body
            captured["headers"] = headers
            captured["forward_url"] = forward_url
            return 200, b'{"status":"success"}', "application/json"

        old_forward = app_module._forward_qq_webhook
        app_module._forward_qq_webhook = fake_forward
        try:
            app = create_app(
                database_url="sqlite:///:memory:",
                bot_token="bot-token",
                admin_token="admin-token",
            )
            client = TestClient(app)
            resp = client.post(
                "/qq",
                content='{"op":0,"t":"GROUP_AT_MESSAGE_CREATE","d":{}}',
                headers={"Content-Type": "application/json"},
            )
        finally:
            app_module._forward_qq_webhook = old_forward

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "success"})
        self.assertIn(b"GROUP_AT_MESSAGE_CREATE", captured["body"])
        self.assertEqual(captured["forward_url"], "http://127.0.0.1:8765/qq")


if __name__ == "__main__":
    unittest.main()
