import unittest
from unittest.mock import AsyncMock, Mock, patch

from handlers import sauth


class Account163ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_163_credentials_posts_quick_endpoint_with_api_key(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "account": "mail@example.com",
            "password": "mail_password",
        }
        client = Mock()
        client.post = AsyncMock(return_value=response)

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_163_credentials()

        self.assertTrue(ok)
        client.post.assert_awaited_once_with(
            sauth.ACCOUNT_163_API,
            headers={"X-Api-Key": sauth.SAUTH_API_KEY},
        )
        self.assertIn("mail@example.com", message)
        self.assertIn("mail_password", message)

    async def test_get_163_credentials_fails_when_response_is_missing_fields(self):
        response = Mock(status_code=200)
        response.json.return_value = {"account": "mail@example.com"}
        client = Mock()
        client.post = AsyncMock(return_value=response)

        with patch.object(sauth, "_get_client", return_value=client):
            ok, message = await sauth.get_163_credentials()

        self.assertFalse(ok)
        self.assertIn("163", message)

    async def test_get_163_stock_reads_inventory_with_admin_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {"total": 3000, "available": 2875, "used": 125}
        client = Mock()
        client.get = AsyncMock(return_value=response)

        with patch.object(sauth, "_get_client", return_value=client):
            ok, available, total, used, error = await sauth.get_163_stock()

        self.assertTrue(ok)
        self.assertEqual((available, total, used, error), (2875, 3000, 125, ""))
        client.get.assert_awaited_once_with(
            sauth.ACCOUNT_163_INVENTORY_API,
            headers={"X-Admin-Token": sauth.SAUTH_ADMIN_TOKEN},
        )


if __name__ == "__main__":
    unittest.main()
