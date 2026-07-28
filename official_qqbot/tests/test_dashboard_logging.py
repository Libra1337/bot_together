import unittest
from unittest.mock import AsyncMock, patch

import bot


class _LoggingBackend:
    def __init__(self):
        self.commands = []
        self.outbound = []

    def log_command(
        self,
        user_key="",
        group_openid="",
        command="",
        content="",
        message_id="",
    ):
        self.commands.append(
            {
                "user_key": user_key,
                "group_openid": group_openid,
                "command": command,
                "content": content,
                "message_id": message_id,
            }
        )

    def log_outbound(
        self,
        user_key="",
        group_openid="",
        channel="",
        status="",
        content="",
        message_id="",
    ):
        self.outbound.append(
            {
                "user_key": user_key,
                "group_openid": group_openid,
                "channel": channel,
                "status": status,
                "content": content,
                "message_id": message_id,
            }
        )


class DashboardLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_backend = bot._state_backend
        self.backend = _LoggingBackend()
        bot._state_backend = self.backend

    def tearDown(self):
        bot._state_backend = self.old_backend

    async def test_handled_command_is_written_to_dashboard_command_log(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(bot, "handle_command", new_callable=AsyncMock) as handle:
            handle.return_value = True
            await bot.process_message(ctx, "/help")

        self.assertEqual(
            self.backend.commands,
            [
                {
                    "user_key": "user-a",
                    "group_openid": "group-a",
                    "command": "/help",
                    "content": "/help",
                    "message_id": "msg-a",
                }
            ],
        )

    async def test_reply_is_written_to_dashboard_outbound_log(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(bot, "send_group_msg", new_callable=AsyncMock) as send_group:
            send_group.return_value = True
            await bot.reply(ctx, "hello")

        self.assertEqual(
            self.backend.outbound,
            [
                {
                    "user_key": "user-a",
                    "group_openid": "group-a",
                    "channel": "group",
                    "status": "success",
                    "content": "hello",
                    "message_id": "msg-a",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
