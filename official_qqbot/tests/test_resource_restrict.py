import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import bot
import shared_cooldown


class ResourceRestrictStorageTests(unittest.TestCase):
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

    def test_restrict_rule_limits_each_user_within_window(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("163", 1, "day")
            blocked, count, limit, window = shared_cooldown.check_restrict_limit(
                "163", "user-a"
            )

        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))

        with patch.object(shared_cooldown.time, "time", return_value=1001):
            shared_cooldown.record_restrict_usage("163", "user-a")
            blocked, count, limit, window = shared_cooldown.check_restrict_limit(
                "163", "user-a"
            )

        self.assertTrue(blocked)
        self.assertEqual((count, limit, window), (1, 1, 86400))

        with patch.object(shared_cooldown.time, "time", return_value=1002):
            blocked, count, _, _ = shared_cooldown.check_restrict_limit("163", "user-b")

        self.assertFalse(blocked)
        self.assertEqual(count, 0)

    def test_restrict_window_expires_old_usage(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("nfa", 1, "min")
            shared_cooldown.record_restrict_usage("nfa", "user-a")

        with patch.object(shared_cooldown.time, "time", return_value=1061):
            blocked, count, limit, window = shared_cooldown.check_restrict_limit(
                "nfa", "user-a"
            )

        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 60))

    def test_restrict_status_reports_reset_after(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("163", 2, "min")
            shared_cooldown.record_restrict_usage("163", "user-a")

        with patch.object(shared_cooldown.time, "time", return_value=1025):
            status = shared_cooldown.get_restrict_status("163", "user-a")

        self.assertFalse(status["blocked"])
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["limit"], 2)
        self.assertEqual(status["window"], 60)
        self.assertEqual(status["reset_after"], 35)

    def test_restrict_usage_stats_cover_standard_ranges(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("163", 10, "day")
            shared_cooldown.record_restrict_usage("163", "user-a")
        with patch.object(shared_cooldown.time, "time", return_value=995):
            shared_cooldown.record_restrict_usage("163", "user-b")

        with patch.object(shared_cooldown.time, "time", return_value=1001):
            stats = shared_cooldown.get_restrict_usage_stats()

        row = next(item for item in stats if item["resource"] == "163")
        self.assertEqual(row["counts"]["second"], 1)
        self.assertEqual(row["counts"]["minute"], 2)
        self.assertEqual(row["counts"]["hour"], 2)
        self.assertEqual(row["limit_count"], 10)

    def test_restrict_usage_survives_process_restart(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("163", 1, "day")
            shared_cooldown.record_restrict_usage("163", "user-a")

        shared_cooldown._cache = {}
        shared_cooldown._last_load_ts = 0

        with patch.object(shared_cooldown.time, "time", return_value=1001):
            blocked, count, limit, window = shared_cooldown.check_restrict_limit(
                "163", "user-a"
            )

        self.assertTrue(blocked)
        self.assertEqual((count, limit, window), (1, 1, 86400))

    def test_reset_restrict_usage_clears_logs_but_keeps_rules(self):
        with patch.object(shared_cooldown.time, "time", return_value=1000):
            shared_cooldown.set_restrict_rule("163", 1, "day")
            shared_cooldown.record_restrict_usage("163", "user-a")

        shared_cooldown.reset_restrict_usage()

        with patch.object(shared_cooldown.time, "time", return_value=1001):
            blocked, count, limit, window = shared_cooldown.check_restrict_limit(
                "163", "user-a"
            )

        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))


class ResourceRestrictCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = "admin-openid"
        self.ctx = {
            "type": "c2c",
            "user_openid": self.user_id,
            "msg_id": "msg-restrict",
        }
        self.old_admins = set(bot._admin_set)
        self.old_state_backend = bot._state_backend
        bot._admin_set.add(self.user_id)

    def tearDown(self):
        bot._admin_set.clear()
        bot._admin_set.update(self.old_admins)
        bot._state_backend = self.old_state_backend

    async def test_restrict_command_sets_rule_for_admin(self):
        with patch.object(bot._shared_cd, "set_restrict_rule") as set_rule, patch.object(
            bot, "reply_plain", new_callable=AsyncMock
        ) as reply_plain:
            handled = await bot.handle_command(self.ctx, "/restrict 163 1 day")

        self.assertTrue(handled)
        set_rule.assert_called_once_with("163", 1, "day")
        reply_plain.assert_awaited_once()

    async def test_reset_limit_command_resets_all_restrict_usage_for_admin(self):
        with patch.object(bot._shared_cd, "reset_restrict_usage") as reset_usage, patch.object(
            bot, "reply_plain", new_callable=AsyncMock
        ) as reply_plain:
            handled = await bot.handle_command(self.ctx, "/resetLimit")

        self.assertTrue(handled)
        reset_usage.assert_called_once_with()
        reply_plain.assert_awaited_once()

    async def test_restricted_4399_does_not_call_upstream(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            return_value={
                "blocked": True,
                "count": 1,
                "limit": 1,
                "window": 86400,
                "reset_after": 3661,
            },
        ), patch.object(bot, "_require_bound_email", new_callable=AsyncMock) as require_email, patch.object(
            bot.sauth, "get_sauth", new_callable=AsyncMock
        ) as get_sauth, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            require_email.return_value = True

            handled = await bot.handle_command(self.ctx, "/4399")

        self.assertTrue(handled)
        get_sauth.assert_not_awaited()
        reply.assert_awaited_once_with(
            self.ctx,
            "已达到获取上限\n当前获取：1/1\n限额刷新：1h1min1s",
        )

    async def test_successful_4399_records_restrict_usage(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            side_effect=[
                {"blocked": False, "count": 0, "limit": 1, "window": 86400, "reset_after": 0},
                {"blocked": True, "count": 1, "limit": 1, "window": 86400, "reset_after": 86400},
            ],
        ), patch.object(bot._state_backend, "record_resource_usage") as record_usage, patch.object(
            bot, "_require_bound_email", new_callable=AsyncMock
        ) as require_email, patch.object(
            bot.sauth, "get_sauth", new_callable=AsyncMock
        ) as get_sauth, patch.object(
            bot, "_send_resource_result", new_callable=AsyncMock
        ) as send_result:
            require_email.return_value = True
            get_sauth.return_value = (True, "token")
            send_result.return_value = True

            handled = await bot.handle_command(self.ctx, "/4399")

        self.assertTrue(handled)
        record_usage.assert_called_once_with("4399", self.user_id)
        self.assertIn("当前获取：1/1", send_result.await_args.kwargs["quota_text"])

    async def test_restricted_nfa_does_not_call_upstream(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            return_value={
                "blocked": True,
                "count": 1,
                "limit": 1,
                "window": 86400,
                "reset_after": 60,
            },
        ), patch.object(bot, "_require_bound_email", new_callable=AsyncMock) as require_email, patch.object(
            bot.nfa, "get_nfa_token", new_callable=AsyncMock
        ) as get_nfa, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            require_email.return_value = True

            handled = await bot.handle_command(self.ctx, "/nfa")

        self.assertTrue(handled)
        get_nfa.assert_not_awaited()
        reply.assert_awaited_once_with(
            self.ctx,
            "已达到获取上限\n当前获取：1/1\n限额刷新：1min0s",
        )

    async def test_restricted_163_does_not_call_upstream(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            return_value={
                "blocked": True,
                "count": 1,
                "limit": 1,
                "window": 86400,
                "reset_after": 59,
            },
        ), patch.object(bot, "_require_bound_email", new_callable=AsyncMock) as require_email, patch.object(
            bot.sauth, "get_163_credentials", new_callable=AsyncMock
        ) as get_163_credentials, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            require_email.return_value = True

            handled = await bot.handle_command(self.ctx, "/163")

        self.assertTrue(handled)
        get_163_credentials.assert_not_awaited()
        reply.assert_awaited_once_with(
            self.ctx,
            "已达到获取上限\n当前获取：1/1\n限额刷新：59s",
        )

    async def test_successful_nfa_records_restrict_usage(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            side_effect=[
                {"blocked": False, "count": 0, "limit": 1, "window": 86400, "reset_after": 0},
                {"blocked": True, "count": 1, "limit": 1, "window": 86400, "reset_after": 86400},
            ],
        ), patch.object(bot._state_backend, "record_resource_usage") as record_usage, patch.object(
            bot._shared_cd, "is_banned", return_value=(False, 0, 0)
        ), patch.object(
            bot._shared_cd, "check_cooldown", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "check_hour_limit", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "record_usage"
        ), patch.object(
            bot, "_require_bound_email", new_callable=AsyncMock
        ) as require_email, patch.object(
            bot.nfa, "get_nfa_token", new_callable=AsyncMock
        ) as get_nfa, patch.object(
            bot, "_send_resource_result", new_callable=AsyncMock
        ) as send_result:
            require_email.return_value = True
            get_nfa.return_value = "主人您的nfa来了喵\nTOKEN"
            send_result.return_value = True

            handled = await bot.handle_command(self.ctx, "/nfa")

        self.assertTrue(handled)
        record_usage.assert_called_once_with("nfa", self.user_id)
        self.assertIn("当前获取：1/1", send_result.await_args.kwargs["quota_text"])

    async def test_successful_163_records_restrict_usage(self):
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            side_effect=[
                {"blocked": False, "count": 0, "limit": 1, "window": 86400, "reset_after": 0},
                {"blocked": True, "count": 1, "limit": 1, "window": 86400, "reset_after": 86400},
            ],
        ), patch.object(bot._state_backend, "record_resource_usage") as record_usage, patch.object(
            bot._shared_cd, "is_banned", return_value=(False, 0, 0)
        ), patch.object(
            bot._shared_cd, "check_cooldown", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "check_hour_limit", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "record_usage"
        ), patch.object(
            bot, "_require_bound_email", new_callable=AsyncMock
        ) as require_email, patch.object(
            bot.sauth, "get_163_credentials", new_callable=AsyncMock
        ) as get_163_credentials, patch.object(
            bot, "_send_resource_result", new_callable=AsyncMock
        ) as send_result:
            require_email.return_value = True
            get_163_credentials.return_value = (True, "account: mail@example.com")
            send_result.return_value = True

            handled = await bot.handle_command(self.ctx, "/163")

        self.assertTrue(handled)
        record_usage.assert_called_once_with("163", self.user_id)
        self.assertIn("当前获取：1/1", send_result.await_args.kwargs["quota_text"])

    async def test_resource_restrict_uses_global_limit_user_id(self):
        self.ctx["limit_user_id"] = "global-user-openid"
        with patch.object(
            bot._state_backend,
            "get_resource_limit_status",
            side_effect=[
                {"blocked": False, "count": 0, "limit": 1, "window": 86400, "reset_after": 0},
                {"blocked": True, "count": 1, "limit": 1, "window": 86400, "reset_after": 86400},
            ],
        ) as check_limit, patch.object(bot._state_backend, "record_resource_usage") as record_usage, patch.object(
            bot._shared_cd, "is_banned", return_value=(False, 0, 0)
        ), patch.object(
            bot._shared_cd, "check_cooldown", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "check_hour_limit", return_value=(False, 0)
        ), patch.object(
            bot._shared_cd, "record_usage"
        ), patch.object(
            bot, "_require_bound_email", new_callable=AsyncMock
        ) as require_email, patch.object(
            bot.sauth, "get_163_credentials", new_callable=AsyncMock
        ) as get_163_credentials, patch.object(
            bot, "_send_resource_result", new_callable=AsyncMock
        ) as send_result:
            require_email.return_value = True
            get_163_credentials.return_value = (True, "account: mail@example.com")
            send_result.return_value = True

            handled = await bot.handle_command(self.ctx, "/163")

        self.assertTrue(handled)
        self.assertEqual(check_limit.call_args_list[0].args, ("163", "global-user-openid"))
        record_usage.assert_called_once_with("163", "global-user-openid")

    async def test_stock_uses_163_inventory_api(self):
        with patch.object(bot.nfa, "get_nfa_stock", new_callable=AsyncMock) as get_nfa_stock, patch.object(
            bot.sauth, "get_4399_stock", new_callable=AsyncMock
        ) as get_4399_stock, patch.object(
            bot.sauth, "get_163_stock", new_callable=AsyncMock
        ) as get_163_stock, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            get_nfa_stock.return_value = (True, 2, "")
            get_4399_stock.return_value = (True, 10, 20, "")
            get_163_stock.return_value = (True, 2875, 3000, 125, "")

            handled = await bot.handle_command(self.ctx, "/stock")

        self.assertTrue(handled)
        message = reply.await_args.args[1]
        self.assertIn("163：2875/3000", message)


if __name__ == "__main__":
    unittest.main()
