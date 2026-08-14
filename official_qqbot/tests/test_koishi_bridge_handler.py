import unittest
from unittest.mock import AsyncMock, patch

import bot


class KoishiBridgeHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._recent_inbound_msg_ids.clear()

    async def test_bridge_payload_is_processed_for_whitelisted_group(self):
        payload = {
            "type": "group",
            "group_openid": "1097445697",
            "user_openid": "user-openid",
            "msg_id": "bridge-msg-1",
            "content": "你好",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            result = await bot.handle_koishi_bridge_payload(payload)

        self.assertEqual(result, {"ok": True, "ignored": False})
        process.assert_awaited_once_with(
            {
                "type": "group",
                "group_openid": "1097445697",
                "user_openid": "user-openid",
                "limit_user_id": "user-openid",
                "msg_id": "bridge-msg-1",
            },
            "你好",
        )

    async def test_bridge_payload_ignores_duplicate_message_id(self):
        payload = {
            "type": "group",
            "group_openid": "1097445697",
            "user_openid": "user-openid",
            "msg_id": "bridge-msg-duplicate",
            "content": "你好",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            first = await bot.handle_koishi_bridge_payload(payload)
            second = await bot.handle_koishi_bridge_payload(payload)

        self.assertEqual(first, {"ok": True, "ignored": False})
        self.assertEqual(second, {"ok": True, "ignored": True, "reason": "duplicate"})
        process.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
