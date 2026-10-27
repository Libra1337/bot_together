import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import bot
import shared_cooldown
from adapters.qq_official import (
    C2C_MESSAGE_CREATE,
    GROUP_AT_MESSAGE_CREATE,
    adapt_message_event,
)


class PointsFileSystemTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_sign_file = bot.SIGN_FILE
        self.old_identity_file = bot.IDENTITY_FILE
        self.old_shared_file = shared_cooldown.SHARED_FILE
        bot.SIGN_FILE = os.path.join(self.tmp.name, "sign_official.json")
        bot.IDENTITY_FILE = os.path.join(self.tmp.name, "identity_map.json")
        shared_cooldown.SHARED_FILE = os.path.join(self.tmp.name, "cooldowns.json")
        shared_cooldown._cache = {}
        shared_cooldown._last_load_ts = 0
        self.old_sign = bot._sign_data
        self.old_identity = bot._identity_map
        bot._sign_data = {}
        bot._identity_map = {}
        if hasattr(bot, "_active_resource_request_keys"):
            bot._active_resource_request_keys.clear()

    def tearDown(self):
        bot._sign_data = self.old_sign
        bot._identity_map = self.old_identity
        bot.SIGN_FILE = self.old_sign_file
        bot.IDENTITY_FILE = self.old_identity_file
        shared_cooldown.SHARED_FILE = self.old_shared_file
        shared_cooldown._cache = {}
        shared_cooldown._last_load_ts = 0
        self.tmp.cleanup()


class SignInTests(PointsFileSystemTestBase):
    async def test_sign_in_awards_flat_50_points(self):
        message = bot.do_sign_in("union-a")
        self.assertIn("获得 50 积分", message)
        self.assertEqual(bot._sign_data["union-a"]["points"], 50)

    async def test_sign_in_only_once_per_day(self):
        bot.do_sign_in("union-a")
        message = bot.do_sign_in("union-a")
        self.assertIn("已经签到", message)
        self.assertEqual(bot._sign_data["union-a"]["points"], 50)

    async def test_balance_command_reports_points(self):
        bot.do_sign_in("union-a")
        text = bot.points_balance_text("union-a")
        self.assertIn("当前积分：50", text)
        self.assertIn("签到 +50/天", text)
        self.assertIn("4399 小号 -2 积分", text)
        self.assertIn("sauth -5 积分", text)
        self.assertIn("163 小号 -50 积分", text)


class GroupAddRewardTests(PointsFileSystemTestBase):
    def _group_event(self, group, operator):
        return {
            "group_openid": group,
            "op_member_openid": operator,
            "id": "event-id",
        }

    async def test_add_to_large_group_awards_25_points(self):
        bot._identity_map["member-a"] = "union-a"
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = 42
            await bot.handle_group_add_robot(self._group_event("group-a", "member-a"))

        self.assertEqual(bot._sign_data["union-a"]["points"], 25)
        self.assertIn("group-a", bot._sign_data["union-a"]["rewarded_groups"])

    async def test_small_group_gets_no_reward(self):
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = bot.GROUP_ADD_MIN_MEMBERS - 1
            await bot.handle_group_add_robot(self._group_event("group-a", "union-a"))

        self.assertNotIn("union-a", bot._sign_data)

    async def test_daily_limit_blocks_after_ten_rewards(self):
        bot._identity_map["member-a"] = "union-a"
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = 99
            for i in range(bot.GROUP_ADD_DAILY_LIMIT + 2):
                await bot.handle_group_add_robot(
                    self._group_event(f"group-{i}", "member-a")
                )

        expected = bot.GROUP_ADD_REWARD_POINTS * bot.GROUP_ADD_DAILY_LIMIT
        self.assertEqual(bot._sign_data["union-a"]["points"], expected)

    async def test_same_group_rewarded_only_once(self):
        bot._identity_map["member-a"] = "union-a"
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = 99
            await bot.handle_group_add_robot(self._group_event("group-a", "member-a"))
            await bot.handle_group_add_robot(self._group_event("group-a", "member-a"))

        self.assertEqual(bot._sign_data["union-a"]["points"], 25)

    async def test_unknown_identity_queues_pending_reward(self):
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = 99
            await bot.handle_group_add_robot(self._group_event("group-a", "member-a"))

        self.assertNotIn("member-a", bot._sign_data)
        pending = bot._identity_map["_pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["member"], "member-a")

    async def test_repeated_add_only_queues_once(self):
        with patch.object(
            bot, "fetch_group_member_count", new_callable=AsyncMock
        ) as fetch_count, patch.object(
            bot, "send_group_msg", new_callable=AsyncMock
        ):
            fetch_count.return_value = 99
            for _ in range(3):
                await bot.handle_group_add_robot(self._group_event("group-a", "member-a"))

        self.assertEqual(len(bot._identity_map["_pending"]), 1)


class PendingNoticeTests(PointsFileSystemTestBase):
    async def test_group_message_triggers_one_time_notice(self):
        bot._identity_map["_pending"] = [
            {"group": "group-a", "member": "member-b", "points": 25, "ts": 1, "notified": False}
        ]
        with patch.object(bot, "send_group_msg", new_callable=AsyncMock) as send_msg:
            send_msg.return_value = True
            await bot.notify_pending_group_reward("group-a", "msg-9")

        send_msg.assert_awaited_once()
        self.assertIn("邀请奖励待领取", send_msg.await_args.args[1])
        self.assertTrue(bot._identity_map["_pending"][0]["notified"])

        with patch.object(bot, "send_group_msg", new_callable=AsyncMock) as send_msg:
            await bot.notify_pending_group_reward("group-a", "msg-10")
        send_msg.assert_not_awaited()

    async def test_notice_failure_retries_next_message(self):
        bot._identity_map["_pending"] = [
            {"group": "group-a", "member": "member-b", "points": 25, "ts": 1, "notified": False}
        ]
        with patch.object(bot, "send_group_msg", new_callable=AsyncMock) as send_msg:
            send_msg.return_value = False
            await bot.notify_pending_group_reward("group-a", "msg-9")
        self.assertFalse(bot._identity_map["_pending"][0]["notified"])


class IdentityResolveTests(PointsFileSystemTestBase):
    def _group_event(self, member="member-a", union="union-a", group="group-a"):
        data = {
            "id": "msg-1",
            "group_openid": group,
            "author": {
                "member_openid": member,
                "union_openid": union,
                "bot": False,
            },
            "content": "/help",
        }
        return adapt_message_event(GROUP_AT_MESSAGE_CREATE, data, set())

    async def test_group_message_builds_union_identity(self):
        event = self._group_event()
        self.assertEqual(event.user_openid, "member-a")
        self.assertEqual(event.limit_user_id, "union-a")

    async def test_c2c_message_prefers_union_openid(self):
        data = {
            "id": "msg-2",
            "author": {
                "user_openid": "c2c-openid",
                "union_openid": "union-a",
                "bot": False,
            },
            "content": "/help",
        }
        event = adapt_message_event(C2C_MESSAGE_CREATE, data, set())
        self.assertEqual(event.user_openid, "c2c-openid")
        self.assertEqual(event.limit_user_id, "union-a")

    async def test_legacy_points_merge_into_union_account(self):
        bot._sign_data["member-a"] = {"points": 120, "streak": 3, "last": ""}
        bot._sign_data["c2c-openid"] = {"points": 30, "streak": 1, "last": ""}

        bot.resolve_message_identity(self._group_event())

        self.assertEqual(bot._sign_data["union-a"]["points"], 120)
        self.assertEqual(bot._identity_map["member-a"], "union-a")

        c2c_event = adapt_message_event(
            C2C_MESSAGE_CREATE,
            {
                "id": "msg-3",
                "author": {
                    "user_openid": "c2c-openid",
                    "union_openid": "union-a",
                    "bot": False,
                },
                "content": "/help",
            },
            set(),
        )
        bot.resolve_message_identity(c2c_event)
        self.assertEqual(bot._sign_data["union-a"]["points"], 150)
        self.assertEqual(bot._sign_data["member-a"].get("merged_into"), "union-a")

    async def test_pending_group_reward_lands_on_first_message(self):
        bot._identity_map["_pending"] = [
            {"group": "group-a", "member": "member-a", "points": 25, "ts": 1}
        ]
        awarded = bot.resolve_message_identity(self._group_event())
        self.assertEqual(awarded, 25)
        self.assertEqual(bot._sign_data["union-a"]["points"], 25)
        self.assertNotIn("_pending", bot._identity_map)


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_file = shared_cooldown.SHARED_FILE
        shared_cooldown.SHARED_FILE = os.path.join(self.tmp.name, "cooldowns.json")
        shared_cooldown._cache = {}
        shared_cooldown._last_load_ts = 0

    def tearDown(self):
        shared_cooldown.SHARED_FILE = self.old_file
        shared_cooldown._cache = {}
        shared_cooldown._last_load_ts = 0
        self.tmp.cleanup()

    def test_sauth_rate_limit_allows_five_per_minute(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            for _ in range(4):
                shared_cooldown.record_rate_usage("sauth", "user-a")
                blocked, used, _ = shared_cooldown.check_rate_limit(
                    "sauth", "user-a", 5, 60
                )
                self.assertFalse(blocked)

            shared_cooldown.record_rate_usage("sauth", "user-a")
            blocked, used, retry = shared_cooldown.check_rate_limit(
                "sauth", "user-a", 5, 60
            )
        self.assertTrue(blocked)
        self.assertEqual(used, 5)
        self.assertGreater(retry, 0)

    def test_rate_window_expires(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            for _ in range(5):
                shared_cooldown.record_rate_usage("sauth", "user-a")

        with patch.object(shared_cooldown.time, "time", return_value=1061):
            blocked, used, _ = shared_cooldown.check_rate_limit(
                "sauth", "user-a", 5, 60
            )
        self.assertFalse(blocked)
        self.assertEqual(used, 0)


class QQBindTests(PointsFileSystemTestBase):
    def setUp(self):
        super().setUp()
        self.old_qq_binds = bot._qq_binds
        bot._qq_binds = {}
        self.old_qq_file = bot.QQ_BIND_FILE
        bot.QQ_BIND_FILE = os.path.join(self.tmp.name, "qq_binds.json")

    def tearDown(self):
        bot._qq_binds = self.old_qq_binds
        bot.QQ_BIND_FILE = self.old_qq_file
        super().tearDown()

    async def test_bind_merges_balance_into_qq_account(self):
        bot._sign_data["member-a"] = {"points": 80, "streak": 2, "last": ""}
        ok, message = bot.bind_qq_account("member-a", "123456789")
        self.assertTrue(ok)
        self.assertEqual(bot._sign_data["QQ123456789"]["points"], 80)
        self.assertEqual(bot._sign_data["member-a"].get("merged_into"), "QQ123456789")
        self.assertEqual(bot._account_key("member-a"), "QQ123456789")
        self.assertIn("123456789", message)

    async def test_same_person_binds_from_second_group(self):
        bot._sign_data["member-a"] = {"points": 80, "streak": 2, "last": ""}
        bot.bind_qq_account("member-a", "123456789")
        bot._sign_data["member-b"] = {"points": 45, "streak": 1, "last": ""}
        ok, message = bot.bind_qq_account("member-b", "123456789")
        self.assertTrue(ok)
        self.assertEqual(bot._sign_data["QQ123456789"]["points"], 125)

    async def test_claimed_qq_accepts_same_person_second_scenario(self):
        bot.bind_qq_account("member-a", "123456789")
        bot._sign_data["member-b"] = {"points": 10, "streak": 0, "last": ""}
        ok, message = bot.bind_qq_account("member-b", "123456789")
        self.assertTrue(ok)
        self.assertEqual(bot._sign_data["QQ123456789"]["points"], 10)
        self.assertEqual(bot._account_key("member-b"), "QQ123456789")
        self.assertEqual(bot._account_key("member-a"), "QQ123456789")

    def _group_event(self, member="member-a", union="union-a", group="group-a"):
        data = {
            "id": "msg-1",
            "group_openid": group,
            "author": {
                "member_openid": member,
                "union_openid": union,
                "bot": False,
            },
            "content": "/help",
        }
        return adapt_message_event(GROUP_AT_MESSAGE_CREATE, data, set())

    async def test_sign_in_after_bind_uses_qq_account(self):
        bot._sign_data["member-a"] = {"points": 10, "streak": 0, "last": ""}
        bot.bind_qq_account("member-a", "123456789")
        bot.do_sign_in(bot._account_key("member-a"))
        self.assertEqual(bot._sign_data["QQ123456789"]["points"], 60)

    async def test_identity_learning_propagates_qq_bind(self):
        bot._qq_binds["member-a"] = "123456789"
        event = self._group_event()
        bot.resolve_message_identity(event)
        self.assertEqual(bot._account_key(event.limit_user_id), "QQ123456789")


class BindQQCommandTests(PointsFileSystemTestBase):
    def setUp(self):
        super().setUp()
        self.old_qq_binds = bot._qq_binds
        self.old_qq_file = bot.QQ_BIND_FILE
        bot._qq_binds = {}
        bot.QQ_BIND_FILE = os.path.join(self.tmp.name, "qq_binds.json")
        self.ctx = {
            "type": "c2c",
            "user_openid": "member-a",
            "msg_id": "msg-bindqq",
            "limit_user_id": "member-a",
        }

    def tearDown(self):
        bot._qq_binds = self.old_qq_binds
        bot.QQ_BIND_FILE = self.old_qq_file
        super().tearDown()

    async def test_bindqq_command_merges_points(self):
        bot._sign_data["member-a"] = {"points": 30, "streak": 0, "last": ""}
        with patch.object(bot, "reply_plain", new_callable=AsyncMock) as reply_plain:
            handled = await bot.handle_command(self.ctx, "/bindqq 10001")

        self.assertTrue(handled)
        self.assertIn("QQ 10001", reply_plain.await_args.args[1])
        self.assertEqual(bot._sign_data["QQ10001"]["points"], 30)

    async def test_bindqq_invalid_input_shows_usage(self):
        with patch.object(bot, "reply", new_callable=AsyncMock) as reply:
            handled = await bot.handle_command(self.ctx, "/bindqq abc")

        self.assertTrue(handled)
        self.assertIn("/bindqq 你的QQ号", reply.await_args.args[1])
        self.assertEqual(bot._qq_binds, {})


class SauthRateGateTests(PointsFileSystemTestBase):
    async def test_over_limit_sauth_replies_and_skips_upstream(self):
        ctx = {
            "type": "c2c",
            "user_openid": "union-a",
            "msg_id": "msg-sauth",
            "limit_user_id": "union-a",
        }
        bot._sign_data["union-a"] = {"points": 100, "streak": 0, "last": ""}
        with patch.object(
            bot._shared_cd, "check_rate_limit", return_value=(True, 5, 37)
        ) as check_rate, patch.object(
            bot.sauth, "get_sauth", new_callable=AsyncMock
        ) as get_sauth, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            handled = await bot.handle_command(ctx, "/sauth")

        self.assertTrue(handled)
        check_rate.assert_called_once_with("sauth", "union-a", 5, 60)
        get_sauth.assert_not_awaited()
        self.assertIn("1 分钟最多 5 次", reply.await_args.args[1])
        self.assertEqual(bot._sign_data["union-a"]["points"], 100)


if __name__ == "__main__":
    unittest.main()
