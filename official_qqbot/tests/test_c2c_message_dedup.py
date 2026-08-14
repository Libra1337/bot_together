import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import bot


class C2CMessageDedupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._recent_inbound_msg_ids.clear()

    async def test_c2c_messages_without_id_are_not_deduplicated(self):
        data = {
            "author": {"user_openid": "user-without-id"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(data)
            await bot.handle_c2c_message(data)

        self.assertEqual(process.await_count, 2)

    async def test_group_and_c2c_message_ids_use_separate_namespaces(self):
        group_data = {
            "group_openid": "shared-openid",
            "id": "shared-message-id",
            "author": {"member_openid": "group-user"},
            "content": "@bot /help",
        }
        c2c_data = {
            "id": "shared-message-id",
            "author": {"user_openid": "shared-openid"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(group_data)
            await bot.handle_c2c_message(c2c_data)

        self.assertEqual(process.await_count, 2)

    async def test_duplicate_official_c2c_message_is_processed_once(self):
        data = {
            "id": "c2c-duplicate",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(data)
            await bot.handle_c2c_message(data)

        process.assert_awaited_once_with(
            {
                "type": "c2c",
                "group_openid": "",
                "user_openid": "private-user",
                "limit_user_id": "private-user",
                "msg_id": "c2c-duplicate",
            },
            "/help",
        )

    async def test_concurrent_duplicate_c2c_message_is_processed_once(self):
        data = {
            "id": "c2c-concurrent-duplicate",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }
        processing_started = asyncio.Event()
        release_processing = asyncio.Event()

        async def block_processing(*_args):
            processing_started.set()
            await release_processing.wait()

        with patch.object(
            bot,
            "process_message",
            new_callable=AsyncMock,
            side_effect=block_processing,
        ) as process:
            first_task = asyncio.create_task(bot.handle_c2c_message(data))
            duplicate_task = None
            assertion_succeeded = False
            try:
                await asyncio.wait_for(processing_started.wait(), timeout=1)
                duplicate_task = asyncio.create_task(bot.handle_c2c_message(data))
                await asyncio.sleep(0)
                self.assertEqual(process.await_count, 1)
                assertion_succeeded = True
            finally:
                release_processing.set()
                tasks = [first_task]
                if duplicate_task is not None:
                    tasks.append(duplicate_task)
                results = await asyncio.gather(*tasks, return_exceptions=True)
                if assertion_succeeded:
                    for result in results:
                        if isinstance(result, BaseException):
                            raise result

    async def test_official_and_koishi_c2c_delivery_is_processed_once(self):
        official_data = {
            "id": "c2c-cross-ingress",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }
        koishi_payload = {
            "type": "c2c",
            "user_openid": "private-user",
            "msg_id": "c2c-cross-ingress",
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(official_data)
            result = await bot.handle_koishi_bridge_payload(koishi_payload)

        self.assertEqual(
            result, {"ok": True, "ignored": True, "reason": "duplicate"}
        )
        process.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
