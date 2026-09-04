import unittest
from unittest.mock import patch

import bot
from handlers.image_gen import GeneratedImage


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _CaptureClient:
    responses = []
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.__class__.calls.append({"url": url, "headers": headers, "json": json})
        return self.__class__.responses.pop(0)


class ImageSendingTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_group_image_uploads_url_then_sends_media_message(self):
        _CaptureClient.responses = [
            _Response(payload={"file_info": "group-file-info"}),
            _Response(status_code=200),
        ]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_group_image(
                "group-a",
                GeneratedImage(url="https://cdn.example.test/image.png"),
                "msg-a",
            )

        self.assertTrue(ok)
        self.assertEqual(
            _CaptureClient.calls[0]["url"],
            f"{bot.API_BASE}/v2/groups/group-a/files",
        )
        self.assertEqual(
            _CaptureClient.calls[0]["json"],
            {
                "file_type": 1,
                "url": "https://cdn.example.test/image.png",
                "srv_send_msg": False,
            },
        )
        self.assertEqual(
            _CaptureClient.calls[1]["url"],
            f"{bot.API_BASE}/v2/groups/group-a/messages",
        )
        self.assertEqual(
            _CaptureClient.calls[1]["json"],
            {
                "msg_type": 7,
                "media": {"file_info": "group-file-info"},
                "msg_id": "msg-a",
                "msg_seq": 1,
            },
        )

    async def test_c2c_image_uploads_base64_then_sends_media_message(self):
        _CaptureClient.responses = [
            _Response(payload={"file_info": "c2c-file-info"}),
            _Response(status_code=200),
        ]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_c2c_image(
                "user-a",
                GeneratedImage(b64_json="YWJj"),
                "msg-b",
            )

        self.assertTrue(ok)
        self.assertEqual(
            _CaptureClient.calls[0]["url"],
            f"{bot.API_BASE}/v2/users/user-a/files",
        )
        self.assertEqual(
            _CaptureClient.calls[0]["json"],
            {"file_type": 1, "file_data": "YWJj", "srv_send_msg": False},
        )
        self.assertEqual(
            _CaptureClient.calls[1]["json"]["media"],
            {"file_info": "c2c-file-info"},
        )

    async def test_upload_failure_does_not_send_second_request(self):
        _CaptureClient.responses = [_Response(status_code=400, text="contains-secret")]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_group_image(
                "group-a", GeneratedImage(url="https://cdn.example.test/a.png"), "msg-a"
            )

        self.assertFalse(ok)
        self.assertEqual(len(_CaptureClient.calls), 1)

    async def test_missing_file_info_does_not_send_second_request(self):
        _CaptureClient.responses = [_Response(payload={"file_uuid": "uuid-only"})]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_c2c_image(
                "user-a", GeneratedImage(b64_json="YWJj"), "msg-a"
            )

        self.assertFalse(ok)
        self.assertEqual(len(_CaptureClient.calls), 1)

    async def test_final_media_send_failure_is_reported(self):
        _CaptureClient.responses = [
            _Response(payload={"file_info": "file-info"}),
            _Response(status_code=500, text="send failed"),
        ]

        with patch.object(bot.httpx, "AsyncClient", _CaptureClient):
            ok = await bot.send_group_image(
                "group-a", GeneratedImage(url="https://cdn.example.test/a.png"), "msg-a"
            )

        self.assertFalse(ok)
        self.assertEqual(len(_CaptureClient.calls), 2)


if __name__ == "__main__":
    unittest.main()
