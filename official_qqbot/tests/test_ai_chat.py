import unittest

from handlers.ai_chat import AIChat


class _Response:
    status_code = 200
    text = "ok"

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _Client:
    is_closed = False

    def __init__(self, response):
        self.response = response

    async def post(self, *args, **kwargs):
        return self.response


class AIChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_reasoning_content_when_content_is_empty(self):
        chat = AIChat(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="deepseek-v4-flash",
            system_prompt="",
        )
        chat._client = _Client(
            _Response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning_content": "reasoning reply",
                            }
                        }
                    ]
                }
            )
        )

        reply = await chat.chat("test_reasoning_content", "hello")

        self.assertEqual(reply, "reasoning reply")
