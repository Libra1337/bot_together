import json
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import bot


class WebhookAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, value in (("APP_ID", "app"), ("APP_SECRET", "test-secret")):
            mock = patch.object(bot, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        app = web.Application()
        app.router.add_post("/qq", bot._receive_qq_webhook)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def headers(self, body):
        timestamp = "1791129600"
        return {
            "Content-Type": "application/json", "X-Bot-Appid": "app",
            "X-Signature-Timestamp": timestamp,
            "X-Signature-Ed25519": bot._qq_webhook_key("test-secret").sign(timestamp.encode() + body).hex(),
        }

    async def test_valid_signed_full_message_dispatches(self):
        body = json.dumps({"op": 0, "t": "GROUP_MESSAGE_CREATE", "d": {"content": "签到"}}, ensure_ascii=False).encode()
        with patch.object(bot, "handle_group_message", new_callable=AsyncMock) as handler:
            response = await self.client.post("/qq", data=body, headers=self.headers(body))
        self.assertEqual(response.status, 200)
        handler.assert_awaited_once_with({"content": "签到"}, "GROUP_MESSAGE_CREATE")

    async def test_unsigned_tampered_wrong_app_and_malformed_signatures_are_rejected(self):
        body = b'{"op":0,"t":"GROUP_MESSAGE_CREATE","d":{}}'
        cases = [
            {"X-Bot-Appid": "app"},
            self.headers(body + b" "),
            {**self.headers(body), "X-Bot-Appid": "other"},
            {**self.headers(body), "X-Signature-Ed25519": "bad-hex"},
        ]
        for headers in cases:
            with self.subTest(headers=list(headers)), patch.object(bot, "handle_group_message", new_callable=AsyncMock) as handler:
                response = await self.client.post("/qq", data=body, headers=headers)
                self.assertEqual(response.status, 403)
                handler.assert_not_awaited()

    async def test_url_verification_handshake_still_works(self):
        response = await self.client.post("/qq", json={
            "op": 13, "d": {"event_ts": "123", "plain_token": "plain"},
        }, headers={"X-Bot-Appid": "app"})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["plain_token"], "plain")
        bot._qq_webhook_key("test-secret").public_key().verify(bytes.fromhex(payload["signature"]), b"123plain")

    async def test_verification_opcode_cannot_dispatch_commands(self):
        with patch.object(bot, "handle_group_message", new_callable=AsyncMock) as handler:
            response = await self.client.post("/qq", json={
                "op": 13, "t": "GROUP_MESSAGE_CREATE", "d": {"content": "/help"},
            }, headers={"X-Bot-Appid": "app"})
        self.assertEqual(response.status, 200)
        handler.assert_not_awaited()
