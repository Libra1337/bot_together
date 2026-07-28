import unittest
from unittest.mock import AsyncMock, patch

import bot


class GroupMessageRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._recent_group_msg_ids.clear()

    async def test_non_at_group_message_is_processed_for_whitelisted_group(self):
        data = {
            "group_openid": "1097445697",
            "id": "msg-whitelist",
            "author": {"member_openid": "user-openid"},
            "content": "hello",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, "GROUP_MESSAGE_CREATE")

        process.assert_awaited_once_with(
            {
                "type": "group",
                "group_openid": "1097445697",
                "user_openid": "user-openid",
                "limit_user_id": "user-openid",
                "msg_id": "msg-whitelist",
            },
            "hello",
        )

    async def test_non_at_group_message_is_ignored_for_non_whitelisted_group(self):
        data = {
            "group_openid": "other-group",
            "id": "msg-other",
            "author": {"member_openid": "user-openid"},
            "content": "hello",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, "GROUP_MESSAGE_CREATE")

        process.assert_not_awaited()

    async def test_at_group_message_is_processed_for_any_group(self):
        data = {
            "group_openid": "other-group",
            "id": "msg-at",
            "author": {"member_openid": "user-openid"},
            "content": "@bot hello",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, "GROUP_AT_MESSAGE_CREATE")

        process.assert_awaited_once_with(
            {
                "type": "group",
                "group_openid": "other-group",
                "user_openid": "user-openid",
                "limit_user_id": "user-openid",
                "msg_id": "msg-at",
            },
            "hello",
        )

    async def test_official_mention_markup_is_stripped_before_processing(self):
        data = {
            "group_openid": "other-group",
            "id": "msg-markup-at",
            "author": {"member_openid": "user-openid"},
            "content": "<@!1903707124> /help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, "GROUP_AT_MESSAGE_CREATE")

        process.assert_awaited_once_with(
            {
                "type": "group",
                "group_openid": "other-group",
                "user_openid": "user-openid",
                "limit_user_id": "user-openid",
                "msg_id": "msg-markup-at",
            },
            "/help",
        )

    async def test_duplicate_group_message_id_is_processed_once(self):
        data = {
            "group_openid": "1097445697",
            "id": "msg-duplicate",
            "author": {"member_openid": "user-openid"},
            "content": "hello",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, "GROUP_MESSAGE_CREATE")
            await bot.handle_group_message(data, "GROUP_AT_MESSAGE_CREATE")

        process.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
