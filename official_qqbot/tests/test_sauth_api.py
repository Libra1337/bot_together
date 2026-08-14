import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from handlers import sauth


def response(status, body=None, headers=None):
    result = Mock(status_code=status)
    result.headers = headers or {}
    if isinstance(body, BaseException):
        result.json.side_effect = body
    else:
        result.json.return_value = body or {}
    return result


class SauthApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(sauth, "_sauth_inflight_users"):
            sauth._sauth_inflight_users.clear()
        if hasattr(sauth, "_sauth_semaphore"):
            sauth._sauth_semaphore = asyncio.Semaphore(10)

    def test_get_sauth_accepts_user_key_for_single_flight(self):
        self.assertIn("user_key", inspect.signature(sauth.get_sauth).parameters)

    async def test_502_makes_exactly_one_post_with_sixty_five_second_timeout(self):
        client = Mock()
        client.post = AsyncMock(return_value=response(502))

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("暂时不稳定", message)
        client.post.assert_awaited_once_with(
            sauth.SAUTH_API,
            headers={"X-Api-Key": sauth.SAUTH_API_KEY},
            timeout=65.0,
        )

    async def test_timeout_makes_exactly_one_post(self):
        client = Mock()
        client.post = AsyncMock(side_effect=httpx.ReadTimeout("late"))

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ), self.assertLogs("QQBot", level="INFO") as captured:
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("请求超时", message)
        self.assertEqual(client.post.await_count, 1)
        rendered = "\n".join(captured.output)
        self.assertIn("status=timeout", rendered)
        self.assertIn("code=transport_timeout", rendered)
        self.assertIn("request_id=none", rendered)
        self.assertIn("attempts=none", rendered)
        self.assertIn("elapsed_ms=", rendered)

    async def test_structured_inventory_404_is_friendly(self):
        client = Mock()
        client.post = AsyncMock(
            return_value=response(
                404,
                {
                    "code": "inventory_empty",
                    "requestId": "req-empty",
                    "attempts": 0,
                },
                {"X-Request-Id": "req-empty"},
            )
        )

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("库存已空", message)
        self.assertIn("req-empty", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_unstructured_404_is_route_unavailable(self):
        client = Mock()
        client.post = AsyncMock(return_value=response(404, ValueError("html")))

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("接口路由不可用", message)
        self.assertNotIn("库存已空", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_structured_429_reports_rate_limit_and_request_id(self):
        client = Mock()
        client.post = AsyncMock(
            return_value=response(
                429,
                {
                    "code": "upstream_rate_limited",
                    "requestId": "req-429",
                    "attempts": 2,
                },
                {"X-Request-Id": "req-429", "Retry-After": "10"},
            )
        )

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("限流", message)
        self.assertIn("10 秒", message)
        self.assertIn("req-429", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_non_rate_limit_429_reports_temporary_instability(self):
        client = Mock()
        client.post = AsyncMock(
            return_value=response(
                429,
                {
                    "code": "upstream_transport_timeout",
                    "requestId": "req-timeout",
                    "attempts": 1,
                },
                {"X-Request-Id": "req-timeout", "Retry-After": "10"},
            )
        )

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("暂时不稳定", message)
        self.assertNotIn("限流", message)
        self.assertNotIn("10 秒", message)
        self.assertIn("req-timeout", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_structured_503_reports_busy(self):
        client = Mock()
        client.post = AsyncMock(
            return_value=response(
                503,
                {
                    "code": "bridge_queue_full",
                    "requestId": "req-503",
                    "attempts": 0,
                },
                {"X-Request-Id": "req-503", "Retry-After": "1"},
            )
        )

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("繁忙", message)
        self.assertIn("req-503", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_structured_failure_logs_only_safe_metadata(self):
        client = Mock()
        client.post = AsyncMock(
            return_value=response(
                503,
                {
                    "code": "proxy_unavailable",
                    "requestId": "req-safe-log",
                    "attempts": 2,
                    "detail": "proxy-password@private-proxy.example",
                },
                {"X-Request-Id": "req-safe-log"},
            )
        )

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ), self.assertLogs("QQBot", level="INFO") as captured:
            await sauth.get_sauth()

        rendered = "\n".join(captured.output)
        self.assertIn("code=proxy_unavailable", rendered)
        self.assertIn("request_id=req-safe-log", rendered)
        self.assertIn("attempts=2", rendered)
        self.assertIn("elapsed_ms=", rendered)
        self.assertNotIn("private-proxy", rendered)
        self.assertNotIn("proxy-password", rendered)

    async def test_500_is_unstable_without_retry(self):
        client = Mock()
        client.post = AsyncMock(return_value=response(500))

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("暂时不稳定", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_connect_error_is_final(self):
        client = Mock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("offline"))

        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth.asyncio, "sleep", new_callable=AsyncMock
        ):
            ok, message = await sauth.get_sauth()

        self.assertFalse(ok)
        self.assertIn("连接服务器失败", message)
        self.assertEqual(client.post.await_count, 1)

    async def test_same_user_second_request_returns_without_post(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def hold_first_post(*_args, **_kwargs):
            if client.post.await_count == 1:
                started.set()
                await release.wait()
            return response(502)

        client = Mock()
        client.post = AsyncMock(side_effect=hold_first_post)
        with patch.object(sauth, "_get_client", return_value=client):
            first = asyncio.create_task(sauth.get_sauth("same-user"))
            await asyncio.wait_for(started.wait(), 1)
            try:
                with self.assertLogs("QQBot", level="INFO") as captured:
                    ok, message = await sauth.get_sauth("same-user")
                self.assertFalse(ok)
                self.assertIn("正在处理", message)
                self.assertEqual(client.post.await_count, 1)
                rendered = "\n".join(captured.output)
                self.assertIn("status=rejected", rendered)
                self.assertIn("code=single_flight", rendered)
                self.assertIn("request_id=none", rendered)
                self.assertIn("attempts=none", rendered)
                self.assertIn("elapsed_ms=", rendered)
                self.assertIn("rejected=single_flight", rendered)
            finally:
                release.set()
                await first

    async def test_eleventh_user_times_out_before_post(self):
        release = asyncio.Event()

        async def hold_first_ten_posts(*_args, **_kwargs):
            if client.post.await_count <= 10:
                await release.wait()
            return response(503)

        client = Mock()
        client.post = AsyncMock(side_effect=hold_first_ten_posts)
        with patch.object(sauth, "_get_client", return_value=client), patch.object(
            sauth, "SAUTH_ADMISSION_TIMEOUT_SECONDS", 0.01, create=True
        ):
            holders = [
                asyncio.create_task(sauth.get_sauth(f"user-{index}"))
                for index in range(10)
            ]
            try:
                for _ in range(100):
                    if client.post.await_count == 10:
                        break
                    await asyncio.sleep(0)
                ok, message = await sauth.get_sauth("user-eleven")
                self.assertFalse(ok)
                self.assertIn("繁忙", message)
                self.assertEqual(client.post.await_count, 10)
            finally:
                release.set()
                await asyncio.gather(*holders)

    async def test_success_releases_user_and_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def post(*_args, **_kwargs):
            if client.post.await_count == 1:
                started.set()
                await release.wait()
                return response(
                    200,
                    {"account": "account", "password": "password", "Sauth": "token"},
                )
            return response(502)

        client = Mock()
        client.post = AsyncMock(side_effect=post)
        with patch.object(sauth, "_get_client", return_value=client):
            first = asyncio.create_task(sauth.get_sauth("success-user"))
            await asyncio.wait_for(started.wait(), 1)
            try:
                self.assertIn(
                    "success-user", getattr(sauth, "_sauth_inflight_users", set())
                )
            finally:
                release.set()
                await first
            await sauth.get_sauth("success-user")

        self.assertEqual(client.post.await_count, 2)
        self.assertNotIn("success-user", sauth._sauth_inflight_users)
        self.assertEqual(sauth._sauth_semaphore._value, 10)

    async def test_http_failure_releases_user_and_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def post(*_args, **_kwargs):
            if client.post.await_count == 1:
                started.set()
                await release.wait()
            return response(502)

        client = Mock()
        client.post = AsyncMock(side_effect=post)
        with patch.object(sauth, "_get_client", return_value=client):
            first = asyncio.create_task(sauth.get_sauth("failure-user"))
            await asyncio.wait_for(started.wait(), 1)
            try:
                self.assertIn(
                    "failure-user", getattr(sauth, "_sauth_inflight_users", set())
                )
            finally:
                release.set()
                await first
            await sauth.get_sauth("failure-user")

        self.assertEqual(client.post.await_count, 2)
        self.assertNotIn("failure-user", sauth._sauth_inflight_users)
        self.assertEqual(sauth._sauth_semaphore._value, 10)

    async def test_exception_releases_user_and_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def post(*_args, **_kwargs):
            if client.post.await_count == 1:
                started.set()
                await release.wait()
                raise RuntimeError("unexpected")
            return response(502)

        client = Mock()
        client.post = AsyncMock(side_effect=post)
        with patch.object(sauth, "_get_client", return_value=client):
            first = asyncio.create_task(sauth.get_sauth("exception-user"))
            await asyncio.wait_for(started.wait(), 1)
            try:
                self.assertIn(
                    "exception-user", getattr(sauth, "_sauth_inflight_users", set())
                )
            finally:
                release.set()
                await first
            await sauth.get_sauth("exception-user")

        self.assertEqual(client.post.await_count, 2)
        self.assertNotIn("exception-user", sauth._sauth_inflight_users)
        self.assertEqual(sauth._sauth_semaphore._value, 10)

    async def test_cancellation_releases_user_and_slot(self):
        started = asyncio.Event()

        async def post(*_args, **_kwargs):
            if client.post.await_count == 1:
                started.set()
                await asyncio.Event().wait()
            return response(502)

        client = Mock()
        client.post = AsyncMock(side_effect=post)
        with patch.object(sauth, "_get_client", return_value=client):
            with self.assertLogs("QQBot", level="INFO") as captured:
                first = asyncio.create_task(sauth.get_sauth("cancel-user"))
                await asyncio.wait_for(started.wait(), 1)
                try:
                    self.assertIn(
                        "cancel-user", getattr(sauth, "_sauth_inflight_users", set())
                    )
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                finally:
                    if not first.done():
                        first.cancel()
                        await asyncio.gather(first, return_exceptions=True)
            rendered = "\n".join(captured.output)
            self.assertIn("status=cancelled", rendered)
            self.assertIn("code=cancelled", rendered)
            self.assertIn("request_id=none", rendered)
            self.assertIn("attempts=none", rendered)
            self.assertIn("elapsed_ms=", rendered)
            await sauth.get_sauth("cancel-user")

        self.assertEqual(client.post.await_count, 2)
        self.assertNotIn("cancel-user", sauth._sauth_inflight_users)
        self.assertEqual(sauth._sauth_semaphore._value, 10)


if __name__ == "__main__":
    unittest.main()
