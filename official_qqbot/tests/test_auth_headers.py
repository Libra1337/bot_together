import unittest

import bot


class AuthHeaderTests(unittest.TestCase):
    def setUp(self):
        self.old_token = bot._access_token
        bot._access_token = "test-access-token"

    def tearDown(self):
        bot._access_token = self.old_token

    def test_bot_api_headers_use_qqbot_token(self):
        headers = bot._build_bot_auth_header()

        self.assertEqual(headers["Authorization"], "QQBot test-access-token")
        self.assertEqual(headers["X-Union-Appid"], bot.APP_ID)
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_gateway_headers_use_bearer_token(self):
        headers = bot._build_gateway_auth_header()

        self.assertEqual(headers["Authorization"], "Bearer test-access-token")
        self.assertEqual(headers["X-Union-Appid"], bot.APP_ID)
        self.assertEqual(headers["Content-Type"], "application/json")


if __name__ == "__main__":
    unittest.main()
