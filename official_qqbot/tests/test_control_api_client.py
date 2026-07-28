import unittest

import httpx

from control_api.client import ControlApiClient


class ControlApiClientTests(unittest.TestCase):
    def test_check_limit_sends_bot_token_and_parses_response(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={"blocked": True, "count": 1, "limit": 1, "window": 86400},
            )

        client = ControlApiClient(
            base_url="http://control",
            bot_token="bot-token",
            transport=httpx.MockTransport(handler),
        )

        result = client.check_resource_limit("163", "user-a")
        self.assertTrue(result["blocked"])
        self.assertEqual(calls[0].headers["x-bot-token"], "bot-token")


if __name__ == "__main__":
    unittest.main()
