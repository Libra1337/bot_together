import unittest
from unittest.mock import AsyncMock, patch

import bot
from adapters.qq_official import adapt_message_event, GROUP_MESSAGE_CREATE


class FullMessageCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._recent_group_msg_ids.clear()
        for name in ("_music_select", "_github_select", "_music_waiting", "_fuzzy_waiting"):
            mock = patch.object(bot, name, {})
            mock.start()
            self.addCleanup(mock.stop)
        whitelist = patch.object(bot, "FULL_MESSAGE_GROUP_IDS", set())
        whitelist.start()
        self.addCleanup(whitelist.stop)
        self.data = {
            "id": "full-msg", "group_openid": "openid-not-a-qq-number",
            "author": {"id": "member", "bot": False}, "content": "/help",
        }

    async def test_documented_payload_reaches_command_without_mention(self):
        with patch.object(bot, "reply", new_callable=AsyncMock) as reply, patch.object(
            bot, "_record_seen_user"
        ), patch.object(bot, "_log_command_event"), patch.object(bot.ai_chat, "chat", new_callable=AsyncMock) as chat:
            await bot.handle_qq_webhook_payload({"op": 0, "t": GROUP_MESSAGE_CREATE, "d": self.data})
        self.assertIn("指令列表", reply.call_args.args[1])
        self.assertEqual(reply.call_args.args[0]["user_openid"], "member")
        chat.assert_not_awaited()

    async def test_plain_commands_are_forwarded_for_any_group(self):
        for command in ("4399", "/4399", "/bind user@example.com", "签到", "点歌 星晴", "搜索GitHub python", "北京天气", "/生图 猫"):
            with self.subTest(command=command), patch.object(bot, "process_message", new_callable=AsyncMock) as process:
                await bot.handle_group_message({**self.data, "id": command, "content": command}, GROUP_MESSAGE_CREATE)
                process.assert_awaited_once()
                self.assertTrue(process.call_args.args[0]["commands_only"])

    async def test_chatter_images_and_other_peoples_mentions_do_not_trigger(self):
        for content in ("今天吃什么", "", "@someone /help", "<@!someone> /help", "https://example.com", "帮我画一张猫"):
            with self.subTest(content=content), patch.object(bot, "process_message", new_callable=AsyncMock) as process:
                await bot.handle_group_message({**self.data, "content": content, "attachments": [
                    {"content_type": "image/png", "url": "https://example.com/cat.png"}
                ]}, GROUP_MESSAGE_CREATE)
                process.assert_not_awaited()
        self.assertFalse(bot._recent_group_msg_ids)

    async def test_full_message_mentioning_bot_behaves_like_at_event(self):
        cases = [
            ("<@1903707124> /help", "/help"),
            ("<@!1903707124> 签到", "签到"),
        ]
        for content, expected in cases:
            with self.subTest(content=content), patch.object(
                bot, "APP_ID", "1903707124"
            ), patch.object(
                bot, "_identity_map", {}
            ), patch.object(
                bot, "process_message", new_callable=AsyncMock
            ) as process:
                await bot.handle_group_message(
                    {**self.data, "id": content, "content": content}, GROUP_MESSAGE_CREATE
                )
                process.assert_awaited_once()
                self.assertEqual(process.call_args.args[1], expected)
                self.assertNotIn("commands_only", process.call_args.args[0])

    async def test_full_message_numeric_mention_helper(self):
        with patch.object(bot, "APP_ID", "1903707124"), patch.object(
            bot, "_identity_map", {}
        ):
            at_bot, rest = bot._split_full_message_at_bot("<@1903707124> 签到", "group-a")
            self.assertTrue(at_bot)
            self.assertEqual(rest, "签到")
            # 未知 32 位 id + 斜杠指令 → 学习并识别为@机器人
            at_bot, rest = bot._split_full_message_at_bot(
                "<@B8142D4E418090CD8D904B00948A3244> /4399", "group-a"
            )
            self.assertTrue(at_bot)
            self.assertEqual(rest, "/4399")
            self.assertEqual(
                bot._identity_map["_bot_mentions"]["group-a"],
                "B8142D4E418090CD8D904B00948A3244",
            )
            # 已学习后，无斜杠指令也能识别
            at_bot, rest = bot._split_full_message_at_bot(
                "<@B8142D4E418090CD8D904B00948A3244> 签到", "group-a"
            )
            self.assertTrue(at_bot)
            self.assertEqual(rest, "签到")
        # 已知成员 openid 的@不是@机器人
        with patch.object(bot, "APP_ID", "1903707124"), patch.object(
            bot, "_identity_map", {"70837E14CB5C03BDE726DA206C96B6C6": "union-x", "_bot_mentions": {}}
        ):
            at_bot, rest = bot._split_full_message_at_bot(
                "<@70837E14CB5C03BDE726DA206C96B6C6> 签到", "group-a"
            )
            self.assertFalse(at_bot)
        at_bot, rest = bot._split_full_message_at_bot("签到", "group-a")
        self.assertFalse(at_bot)

    async def test_ignored_full_event_does_not_suppress_later_at_event(self):
        data = {**self.data, "content": "你好"}
        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(data, GROUP_MESSAGE_CREATE)
            await bot.handle_group_message(data, bot.GROUP_AT_MESSAGE_CREATE)
        process.assert_awaited_once()
        self.assertNotIn("commands_only", process.call_args.args[0])

    async def test_unknown_slash_command_does_not_fall_through_to_ai(self):
        ctx = adapt_message_event(GROUP_MESSAGE_CREATE, self.data, set()).to_ctx()
        with patch.object(bot, "_record_seen_user"), patch.object(bot, "handle_command", new_callable=AsyncMock, return_value=False), patch.object(
            bot, "_find_fuzzy", return_value=None
        ), patch.object(bot.ai_chat, "chat", new_callable=AsyncMock) as chat:
            await bot.process_message(ctx, "/this-is-not-a-command")
        chat.assert_not_awaited()

    def test_bot_authored_full_messages_are_ignored(self):
        self.data["author"]["bot"] = True
        self.assertIsNone(adapt_message_event(GROUP_MESSAGE_CREATE, self.data, set()))

    def test_followups_are_limited_to_originating_group_and_timeout(self):
        ctx = adapt_message_event(GROUP_MESSAGE_CREATE, self.data, set()).to_ctx()
        bot._music_select["member"] = {"ctx": ctx, "ts": bot._time_mod.time()}
        self.assertTrue(bot._is_group_command(ctx, "1"))
        self.assertFalse(bot._is_group_command({**ctx, "group_openid": "another-group"}, "1"))
        bot._music_select["member"]["ts"] -= 121
        self.assertFalse(bot._is_group_command(ctx, "1"))

    async def test_bridge_with_empty_whitelist_accepts_commands(self):
        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            result = await bot.handle_koishi_bridge_payload({
                "type": "group", "group_openid": "new-group", "user_openid": "member",
                "msg_id": "bridge-new", "event_type": GROUP_MESSAGE_CREATE, "content": "/help",
            })
        self.assertFalse(result["ignored"])
        process.assert_awaited_once()
        self.assertTrue(process.call_args.args[0]["commands_only"])
