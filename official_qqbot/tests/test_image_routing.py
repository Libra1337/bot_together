import unittest
from unittest.mock import AsyncMock, patch

import bot
from handlers.image_gen import GeneratedImage


class _Generator:
    def __init__(self, *, configured=True, result=None):
        self.configured = configured
        self.result = result or (GeneratedImage(url="https://cdn.example.test/a.png"), "")
        self.calls = []

    async def generate(self, prompt):
        self.calls.append(prompt)
        return self.result


class ImageRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_enabled = getattr(bot, "IMAGE_AI_ENABLED", None)
        self.old_cooldown = getattr(bot, "IMAGE_AI_COOLDOWN_SECONDS", None)
        self.old_generator = getattr(bot, "image_generator", None)
        if hasattr(bot, "_image_cooldowns"):
            bot._image_cooldowns.clear()

    def tearDown(self):
        if self.old_enabled is not None:
            bot.IMAGE_AI_ENABLED = self.old_enabled
        if self.old_cooldown is not None:
            bot.IMAGE_AI_COOLDOWN_SECONDS = self.old_cooldown
        if self.old_generator is not None:
            bot.image_generator = self.old_generator
        if hasattr(bot, "_image_cooldowns"):
            bot._image_cooldowns.clear()

    async def test_explicit_command_without_prompt_shows_usage(self):
        bot.IMAGE_AI_ENABLED = True
        bot.image_generator = _Generator()
        ctx = {"type": "c2c", "user_openid": "user-a", "msg_id": "msg-a"}

        with patch.object(bot, "reply", new=AsyncMock()) as reply:
            handled = await bot.handle_image_request(ctx, "/生图")

        self.assertTrue(handled)
        reply.assert_awaited_once_with(ctx, "请在 /生图 后面填写图片描述\n例如：/生图 雨夜里的重庆")
        self.assertEqual(bot.image_generator.calls, [])

    async def test_disabled_image_generation_does_not_call_upstream(self):
        bot.IMAGE_AI_ENABLED = False
        bot.image_generator = _Generator()
        ctx = {"type": "c2c", "user_openid": "user-a", "msg_id": "msg-a"}

        with patch.object(bot, "reply", new=AsyncMock()) as reply:
            handled = await bot.handle_image_request(ctx, "帮我画一张星空")

        self.assertTrue(handled)
        self.assertIn("尚未启用", reply.await_args.args[1])
        self.assertEqual(bot.image_generator.calls, [])

    async def test_unconfigured_image_generation_does_not_call_upstream(self):
        bot.IMAGE_AI_ENABLED = True
        bot.image_generator = _Generator(configured=False)
        ctx = {"type": "c2c", "user_openid": "user-a", "msg_id": "msg-a"}

        with patch.object(bot, "reply", new=AsyncMock()) as reply:
            handled = await bot.handle_image_request(ctx, "帮我画一张星空")

        self.assertTrue(handled)
        self.assertIn("尚未配置", reply.await_args.args[1])
        self.assertEqual(bot.image_generator.calls, [])

    async def test_successful_generation_sends_progress_then_image(self):
        bot.IMAGE_AI_ENABLED = True
        bot.IMAGE_AI_COOLDOWN_SECONDS = 60
        bot.image_generator = _Generator()
        ctx = {
            "type": "group",
            "group_openid": "group-a",
            "user_openid": "member-a",
            "limit_user_id": "global-user-a",
            "msg_id": "msg-a",
        }

        with patch.object(bot, "reply", new=AsyncMock()) as reply, patch.object(
            bot, "reply_image", new=AsyncMock(return_value=True)
        ) as reply_image, patch.object(bot._time_mod, "monotonic", return_value=100):
            handled = await bot.handle_image_request(ctx, "帮我画一张蓝色星空")

        self.assertTrue(handled)
        self.assertEqual(bot.image_generator.calls, ["蓝色星空"])
        self.assertIn("正在生成", reply.await_args_list[0].args[1])
        reply_image.assert_awaited_once()

    async def test_group_and_private_contexts_share_limit_user_cooldown(self):
        bot.IMAGE_AI_ENABLED = True
        bot.IMAGE_AI_COOLDOWN_SECONDS = 60
        bot.image_generator = _Generator()
        group_ctx = {
            "type": "group",
            "group_openid": "group-a",
            "user_openid": "member-a",
            "limit_user_id": "same-global-user",
            "msg_id": "msg-a",
        }
        private_ctx = {
            "type": "c2c",
            "user_openid": "private-openid",
            "limit_user_id": "same-global-user",
            "msg_id": "msg-b",
        }

        with patch.object(bot, "reply", new=AsyncMock()) as reply, patch.object(
            bot, "reply_image", new=AsyncMock(return_value=True)
        ), patch.object(bot._time_mod, "monotonic", side_effect=[100, 101]):
            self.assertTrue(await bot.handle_image_request(group_ctx, "/生图 第一张"))
            self.assertTrue(await bot.handle_image_request(private_ctx, "/生图 第二张"))

        self.assertEqual(bot.image_generator.calls, ["第一张"])
        self.assertIn("59 秒", reply.await_args_list[-1].args[1])

    async def test_image_route_stops_normal_chat_ai(self):
        ctx = {"type": "c2c", "user_openid": "user-a", "msg_id": "msg-a"}

        with patch.object(bot, "_record_seen_user"), patch.object(
            bot, "handle_command", new=AsyncMock(return_value=False)
        ), patch.object(bot, "check_weather", new=AsyncMock(return_value=False)), patch.object(
            bot, "check_links", new=AsyncMock(return_value=False)
        ), patch.object(
            bot, "handle_image_request", new=AsyncMock(return_value=True)
        ) as image_route, patch.object(bot.ai_chat, "chat", new=AsyncMock()) as chat:
            await bot.process_message(ctx, "帮我画一张星空")

        image_route.assert_awaited_once_with(ctx, "帮我画一张星空")
        chat.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
