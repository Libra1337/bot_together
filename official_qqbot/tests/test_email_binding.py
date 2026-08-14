import unittest
from unittest.mock import AsyncMock, patch

import bot


class _EmailBindingBackend:
    def __init__(self):
        self.bindings = {}

    def get_email_binding(self, user_key: str) -> str:
        return self.bindings.get(user_key, "")

    def set_email_binding(self, user_key: str, email: str) -> None:
        self.bindings[user_key] = email

    def delete_email_binding(self, user_key: str) -> bool:
        return self.bindings.pop(user_key, None) is not None

    def is_banned(self, user_key: str) -> bool:
        return False


class EmailBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_bind_accepts_qq_number_as_qq_email(self):
        backend = _EmailBindingBackend()
        ctx = {
            "type": "c2c",
            "user_openid": "openid-a",
            "msg_id": "msg-a",
        }

        with patch.object(bot, "_state_backend", backend), patch.object(
            bot, "reply_plain", new_callable=AsyncMock
        ) as reply_plain, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            handled = await bot.handle_command(ctx, "/bind 123456789")

        self.assertTrue(handled)
        self.assertEqual(backend.bindings.get("openid-a"), "123456789@qq.com")
        reply_plain.assert_awaited_once()
        reply.assert_not_awaited()

    async def test_group_resource_uses_private_bound_qq_email(self):
        backend = _EmailBindingBackend()
        private_ctx = {
            "type": "c2c",
            "user_openid": "openid-a",
            "msg_id": "msg-private",
        }
        group_ctx = {
            "type": "group",
            "user_openid": "openid-a",
            "group_openid": "group-a",
            "msg_id": "msg-group",
        }

        with patch.object(bot, "_state_backend", backend), patch.object(
            bot, "reply_plain", new_callable=AsyncMock
        ), patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply, patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "_get_active_ads", return_value=[]
        ):
            send_email.return_value = (True, "")

            await bot.handle_command(private_ctx, "/bind 123456789")
            ok = await bot._send_resource_result(
                group_ctx,
                "openid-a",
                "163",
                "163 小号",
                "Miracle 163 小号",
                "account: demo\npassword: secret",
            )

        self.assertTrue(ok)
        self.assertEqual(send_email.await_args.args[0], "123456789@qq.com")
        reply.assert_awaited_once()
