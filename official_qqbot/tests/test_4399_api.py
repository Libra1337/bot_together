import unittest
from unittest.mock import AsyncMock, Mock, patch

from handlers import sauth


class Account4399ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_4399_credentials_uses_credentials_endpoint(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "account": "4399-user",
            "password": "4399-password",
            "Sauth": "should-not-be-sent",
        }
        client = Mock()
        client.post = AsyncMock(return_value=response)

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_4399_credentials()

        self.assertTrue(ok)
        client.post.assert_awaited_once_with(
            sauth.ACCOUNT_4399_API,
            headers={"X-Api-Key": sauth.SAUTH_API_KEY},
        )
        self.assertIn("4399-user", message)
        self.assertIn("4399-password", message)
        self.assertNotIn("should-not-be-sent", message)

    async def test_get_sauth_returns_only_sauth_value(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "account": "4399-user",
            "password": "4399-password",
            "Sauth": "sauth-token",
        }
        client = Mock()
        client.post = AsyncMock(return_value=response)

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_sauth()

        self.assertTrue(ok)
        self.assertIn("sauth-token", message)
        self.assertNotIn("4399-user", message)
        self.assertNotIn("4399-password", message)


if __name__ == "__main__":
    unittest.main()
