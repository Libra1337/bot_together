import unittest

import bot


class _MissingTokenResponse:
    status_code = 200
    text = '{"error":"bad credentials"}'

    def json(self):
        return {"error": "bad credentials"}


class _MissingTokenClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _MissingTokenResponse()


class TokenRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_access_token_response_raises_clear_error(self):
        old_client = bot.httpx.AsyncClient
        bot.httpx.AsyncClient = _MissingTokenClient
        try:
            with self.assertRaisesRegex(RuntimeError, "access_token"):
                await bot.refresh_access_token()
        finally:
            bot.httpx.AsyncClient = old_client


if __name__ == "__main__":
    unittest.main()
