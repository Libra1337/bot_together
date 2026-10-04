import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import bot


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _CaptureClient:
    responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.responses:
            return self.responses.pop(0)
        return _Response(200, "ok")


class MarkdownSendingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_token = bot._access_token
        self.old_expire = bot._token_expire_at
        self.old_seq = dict(bot._msg_seq_counter)
        bot._access_token = "token"
        bot._token_expire_at = 9999999999
        bot._msg_seq_counter.clear()
        _CaptureClient.calls = []
        _CaptureClient.responses = []

    def tearDown(self):
        bot._access_token = self.old_token
        bot._token_expire_at = self.old_expire
        bot._msg_seq_counter.clear()
        bot._msg_seq_counter.update(self.old_seq)

    async def test_group_message_uses_markdown_payload_by_default(self):
        _CaptureClient.responses = [_Response(200, "ok")]

        with patch.object(bot, "_append_ads", side_effect=lambda text: text), patch.object(
            bot.httpx, "AsyncClient", _CaptureClient
        ):
            ok = await bot.send_group_msg("group-a", "标题\n内容", "msg-a")

        self.assertTrue(ok)
        payload = _CaptureClient.calls[0]["json"]
        self.assertEqual(payload["msg_type"], 2)
        self.assertEqual(payload["markdown"]["content"], "标题\n内容")
        self.assertEqual(payload["msg_id"], "msg-a")
        self.assertNotIn("content", payload)

    async def test_leading_blank_lines_are_removed_for_group_private_and_fallback(self):
        for send, target in ((bot.send_group_msg, "group-a"), (bot.send_c2c_msg, "user-a")):
            for fallback in (False, True):
                with self.subTest(send=send.__name__, fallback=fallback):
                    _CaptureClient.calls = []
                    _CaptureClient.responses = [_Response(400), _Response(200)] if fallback else [_Response(200)]
                    with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
                        ok = await send(target, "\ufeff\r\n \t\u200b\r\n## 标题\r\n\r\n正文  \r\n下一行", "blank-msg")
                    self.assertTrue(ok)
                    expected = "## 标题\n\n正文  \n下一行"
                    self.assertEqual(_CaptureClient.calls[0]["json"]["markdown"]["content"], expected)
                    if fallback:
                        self.assertEqual(_CaptureClient.calls[1]["json"]["content"], expected)

    def test_markdown_normalization_preserves_code_indentation_and_inner_blank_lines(self):
        payload = bot._build_markdown_payload("\n    code\n\n    more code\n", "msg", 1)
        self.assertEqual(payload["markdown"]["content"], "    code\n\n    more code\n")

    async def test_private_message_uses_markdown_payload_by_default(self):
        _CaptureClient.responses = [_Response(200, "ok")]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_c2c_msg("user-a", "## 标题\n正文", "msg-a")

        self.assertTrue(ok)
        payload = _CaptureClient.calls[0]["json"]
        self.assertEqual(payload["msg_type"], 2)
        self.assertEqual(payload["markdown"]["content"], "## 标题\n正文")
        self.assertEqual(payload["msg_id"], "msg-a")
        rows = payload["keyboard"]["content"]["rows"]
        self.assertEqual([len(row["buttons"]) for row in rows], [3, 2])

    async def test_resource_confirmation_keeps_markdown_without_leading_blank_line(self):
        ctx = {"type": "group", "group_openid": "group-a", "user_openid": "user-a", "msg_id": "msg-a"}
        with patch.object(bot, "_get_bound_email", return_value="255555@qq.com"), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock, return_value=(True, "")
        ), patch.object(bot, "_log_email_outbound"), patch.object(bot, "_log_outbound_event"), patch.object(
            bot.httpx, "AsyncClient", _CaptureClient
        ):
            ok = await bot._send_resource_result(
                ctx, "user-a", "sauth", "4399 Sauth", "Sauth", "resource",
                quota_text="当前获取：1/10\n限额刷新：59s",
            )
        self.assertTrue(ok)
        payload = _CaptureClient.calls[0]["json"]
        self.assertEqual(payload["msg_type"], 2)
        self.assertIn("keyboard", payload)
        self.assertEqual(payload["markdown"]["content"],
            "4399 Sauth 已发送到邮箱 25\\*\\*\\*5@qq。com，请查收喵~\n当前获取：1/10\n限额刷新：59s")

    async def test_markdown_message_does_not_append_ads(self):
        _CaptureClient.responses = [_Response(200, "ok")]

        with patch.object(
            bot,
            "_get_active_ads",
            return_value=["广告 A 完整内容"],
        ), patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_group_msg("group-a", "标题\n内容", "msg-a")

        self.assertTrue(ok)
        payload = _CaptureClient.calls[0]["json"]
        self.assertEqual(payload["markdown"]["content"], "标题\n内容")
        self.assertNotIn("广告 A 完整内容", payload["markdown"]["content"])

    async def test_group_message_adds_default_resource_buttons(self):
        _CaptureClient.responses = [_Response(200, "ok")]

        with patch.object(bot, "_append_ads", side_effect=lambda text: text), patch.object(
            bot.httpx, "AsyncClient", _CaptureClient
        ):
            ok = await bot.send_group_msg("group-a", "hello", "msg-a")

        self.assertTrue(ok)
        payload = _CaptureClient.calls[0]["json"]
        rows = payload["keyboard"]["content"]["rows"]
        self.assertEqual([len(row["buttons"]) for row in rows], [3, 2])
        buttons = [
            button
            for row in rows
            for button in row["buttons"]
        ]
        self.assertEqual(
            [button["render_data"]["label"] for button in buttons],
            ["获取4399", "获取Sauth", "获取163", "查询库存", "快捷绑定"],
        )
        self.assertEqual(
            [button["action"]["data"] for button in buttons],
            ["/4399", "/sauth", "/163", "/查库存", "/bind"],
        )
        self.assertEqual(
            [button["render_data"]["style"] for button in buttons],
            [1, 1, 1, 1, 1],
        )

    async def test_group_message_falls_back_to_text_when_markdown_fails(self):
        _CaptureClient.responses = [
            _Response(400, "markdown rejected"),
            _Response(200, "ok"),
        ]

        with patch.object(bot, "_append_ads", side_effect=lambda text: text), patch.object(
            bot.httpx, "AsyncClient", _CaptureClient
        ):
            ok = await bot.send_group_msg("group-a", "hello", "msg-a")

        self.assertTrue(ok)
        self.assertEqual(len(_CaptureClient.calls), 2)
        markdown_payload = _CaptureClient.calls[0]["json"]
        text_payload = _CaptureClient.calls[1]["json"]
        self.assertEqual(markdown_payload["msg_type"], 2)
        self.assertEqual(text_payload["msg_type"], 0)
        self.assertEqual(text_payload["content"], "hello")
        self.assertEqual(text_payload["msg_seq"], 2)

    def test_markdown_payload_can_include_inline_keyboard(self):
        keyboard = bot._build_inline_keyboard(
            [
                [
                    bot._command_button("status", "查看状态", "/status"),
                    bot._command_button("stock", "查看库存", "/stock"),
                ]
            ]
        )

        payload = bot._build_markdown_payload("## 测试卡片", "msg-a", 1, keyboard)

        self.assertEqual(payload["msg_type"], 2)
        self.assertEqual(payload["markdown"]["content"], "## 测试卡片")
        self.assertEqual(payload["keyboard"], keyboard)
        buttons = payload["keyboard"]["content"]["rows"][0]["buttons"]
        self.assertEqual(buttons[0]["render_data"]["label"], "查看状态")
        self.assertEqual(buttons[0]["action"]["type"], 2)
        self.assertEqual(buttons[0]["action"]["data"], "/status")
        self.assertEqual(buttons[0]["action"]["permission"], {"type": 2})

    async def test_mdtest_command_sends_keyboard_markdown_card(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "reply_markdown_card", new_callable=AsyncMock
        ) as reply_card:
            handled = await bot.handle_command(ctx, "/mdtest")

        self.assertTrue(handled)
        reply_card.assert_awaited_once()
        args = reply_card.await_args.args
        self.assertIs(args[0], ctx)
        self.assertIn("## Markdown 测试", args[1])
        labels = [
            button["render_data"]["label"]
            for row in args[2]
            for button in row
        ]
        self.assertEqual(labels, ["查看状态", "查看库存", "帮助"])

    def test_append_ads_uses_one_random_ad_slot(self):
        with patch.object(
            bot,
            "_get_active_ads",
            return_value=["广告 A 完整内容", "广告 B 完整内容", "广告 C 完整内容"],
        ), patch.object(bot.random, "choice", return_value="广告 B 完整内容"):
            message = bot._append_ads("正文内容")

        self.assertIn("正文内容", message)
        self.assertIn("广告 B 完整内容", message)
        self.assertNotIn("广告 A 完整内容", message)
        self.assertNotIn("广告 C 完整内容", message)

    def test_refresh_ads_expires_items_loaded_from_file(self):
        old_ads_file = bot.ADS_FILE
        old_ads = list(bot._ads)
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/ads.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    [
                        {
                            "id": 1,
                            "content": "过期广告",
                            "enabled": True,
                            "active_until": 1,
                        }
                    ],
                    f,
                    ensure_ascii=False,
                )
            bot.ADS_FILE = path
            try:
                ads = bot._refresh_ads_from_file()
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
            finally:
                bot.ADS_FILE = old_ads_file
                bot._ads = old_ads

        self.assertFalse(ads[0]["enabled"])
        self.assertFalse(saved[0]["enabled"])

    def test_full_ads_are_appended_to_email_body(self):
        with patch.object(
            bot,
            "_get_active_ads",
            return_value=["广告 A 完整内容", "广告 B 完整内容"],
        ):
            body = bot._append_full_ads_to_email("账号：demo\n密码：secret")

        self.assertIn("账号：demo", body)
        self.assertIn("完整赞助信息", body)
        self.assertIn("广告 A 完整内容", body)
        self.assertIn("广告 B 完整内容", body)

    def test_email_html_separates_resource_details_and_ads(self):
        html = bot.email_sender._build_html(
            "Miracle 4399 Sauth",
            (
                "Ciallo 主人您要的东西来啦~\n"
                "账号：demo\n"
                "密码：secret\n"
                "━━━━━━━━━━━━━━\n"
                "完整赞助信息\n"
                "1. 广告 A 完整内容\n"
                "2. 广告 B 完整内容"
            ),
        )

        self.assertIn("资源详情", html)
        self.assertIn("赞助信息", html)
        self.assertIn("广告 A 完整内容", html)
        self.assertLess(html.index("资源详情"), html.index("赞助信息"))

    def test_email_html_uses_distinct_typography_and_spacing(self):
        html = bot.email_sender._build_html(
            "Miracle 4399 Sauth",
            "账号：demo\n密码：secret\nsauth：long-token-value",
        )

        self.assertIn("font-family:-apple-system", html)
        self.assertIn("'PingFang SC'", html)
        self.assertIn("'Microsoft YaHei'", html)
        self.assertIn("font-size:24px;font-weight:800;line-height:1.25", html)
        self.assertIn("font-size:13px;line-height:1.5;font-weight:500", html)
        self.assertIn("width:96px", html)
        self.assertIn("padding:12px 0", html)
        self.assertIn("line-height:1.7;font-family:Consolas", html)

    def test_email_time_is_rendered_as_beijing_time(self):
        rendered = bot.email_sender._format_beijing_time(
            datetime(2026, 5, 28, 9, 31, 29, tzinfo=timezone.utc)
        )

        self.assertEqual(rendered, "2026年05月28日 17:31:29")

    def test_limit_refresh_duration_uses_short_seconds_format(self):
        self.assertEqual(bot._format_duration_cn(84203), "23h23min23s")
        self.assertEqual(bot._format_duration_cn(60), "1min0s")
        self.assertEqual(bot._format_duration_cn(59), "59s")

    async def test_resource_email_sends_full_ads_in_body(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value="user@example.com"
        ), patch.object(
            bot,
            "_get_active_ads",
            return_value=["广告 A 完整内容", "广告 B 完整内容"],
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            send_email.return_value = (True, "")

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "nfa",
                "NFA",
                "资源领取",
                "账号：demo\n密码：secret",
            )

        self.assertTrue(ok)
        send_email.assert_awaited_once()
        email_body = send_email.await_args.args[2]
        self.assertIn("账号：demo", email_body)
        self.assertIn("完整赞助信息", email_body)
        self.assertIn("广告 A 完整内容", email_body)
        self.assertIn("广告 B 完整内容", email_body)
        reply.assert_awaited_once()

    async def test_resource_success_sends_quota_to_email_and_markdown_reply(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value="user@example.com"
        ), patch.object(
            bot,
            "_get_active_ads",
            return_value=[],
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            send_email.return_value = (True, "")

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "163",
                "163 小号",
                "资源领取",
                "账号：demo\n密码：secret",
                quota_text="当前获取：3/3\n限额刷新：1小时后",
            )

        self.assertTrue(ok)
        email_body = send_email.await_args.args[2]
        self.assertIn("账号：demo", email_body)
        self.assertIn("当前获取：3/3", email_body)
        self.assertIn("限额刷新：1小时后", email_body)
        reply_text = reply.await_args.args[1]
        self.assertIn("163 小号 已发送到邮箱", reply_text)
        self.assertIn("当前获取：3/3", reply_text)
        self.assertIn("限额刷新：1小时后", reply_text)


    async def test_private_resource_message_sends_direct_reply_with_ads_without_email(self):
        ctx = {
            "type": "c2c",
            "user_openid": "user-a",
            "group_openid": "",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value="user@example.com"
        ), patch.object(
            bot,
            "_get_active_ads",
            return_value=["ad-a", "ad-b"],
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            reply.return_value = True
            send_email.return_value = (True, "")

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "163",
                "163 小号",
                "Miracle 163 小号",
                "account: demo\npassword: secret",
                quota_text="当前获取: 1/3\n额度刷新: 23h23min23s",
            )

        self.assertTrue(ok)
        send_email.assert_not_awaited()
        reply.assert_awaited_once()
        reply_text = reply.await_args.args[1]
        self.assertIn("account: demo", reply_text)
        self.assertIn("password: secret", reply_text)
        self.assertIn("当前获取: 1/3", reply_text)
        self.assertIn("额度刷新: 23h23min23s", reply_text)
        self.assertIn("ad-a", reply_text)
        self.assertIn("ad-b", reply_text)

    async def test_private_resource_message_falls_back_to_email_when_reply_fails(self):
        ctx = {
            "type": "c2c",
            "user_openid": "user-a",
            "group_openid": "",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value="user@example.com"
        ), patch.object(
            bot,
            "_get_active_ads",
            return_value=["ad-a"],
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            send_email.return_value = (True, "")
            events = []

            def record_reply(*args, **kwargs):
                events.append("reply")
                return False

            def record_email(*args, **kwargs):
                events.append("email")
                return (True, "")

            reply.side_effect = record_reply
            send_email.side_effect = record_email

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "163",
                "163 小号",
                "Miracle 163 小号",
                "account: demo\npassword: secret",
                quota_text="当前获取: 1/3",
            )

        self.assertTrue(ok)
        self.assertEqual(events, ["reply", "email"])
        send_email.assert_awaited_once()
        email_body = send_email.await_args.args[2]
        self.assertIn("account: demo", email_body)
        self.assertIn("ad-a", email_body)
        reply.assert_awaited_once()

    async def test_private_resource_message_without_email_fails_when_reply_fails(self):
        ctx = {
            "type": "c2c",
            "user_openid": "user-a",
            "group_openid": "",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value=""
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            reply.return_value = False

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "163",
                "163 小号",
                "Miracle 163 小号",
                "account: demo\npassword: secret",
                quota_text="当前获取: 1/3",
            )

        self.assertFalse(ok)
        reply.assert_awaited_once()
        send_email.assert_not_awaited()

    async def test_group_resource_email_failure_does_not_post_resource_to_chat(self):
        ctx = {
            "type": "group",
            "user_openid": "user-a",
            "group_openid": "group-a",
            "msg_id": "msg-a",
        }

        with patch.object(
            bot, "_get_bound_email", return_value="user@example.com"
        ), patch.object(
            bot,
            "_get_active_ads",
            return_value=["ad-a"],
        ), patch.object(
            bot, "_send_result_email", new_callable=AsyncMock
        ) as send_email, patch.object(
            bot, "reply", new_callable=AsyncMock
        ) as reply:
            send_email.return_value = (False, "smtp down")

            ok = await bot._send_resource_result(
                ctx,
                "user-a",
                "163",
                "163 小号",
                "Miracle 163 小号",
                "account: demo\npassword: secret",
                quota_text="当前获取: 1/3",
            )

        self.assertFalse(ok)
        reply.assert_awaited_once()
        reply_text = reply.await_args.args[1]
        self.assertIn("邮件发送失败", reply_text)
        self.assertNotIn("account: demo", reply_text)
        self.assertNotIn("password: secret", reply_text)
        self.assertNotIn("ad-a", reply_text)


if __name__ == "__main__":
    unittest.main()
