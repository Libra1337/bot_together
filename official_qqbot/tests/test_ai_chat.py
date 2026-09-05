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
        self.requests = []

    async def post(self, *args, **kwargs):
        self.requests.append((args, kwargs))
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

    async def test_sends_current_images_as_multimodal_content_only_once(self):
        chat = AIChat(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="grok-4.6",
            system_prompt="",
        )
        client = _Client(
            _Response({"choices": [{"message": {"content": "看到了"}}]})
        )
        chat._client = client

        await chat.chat(
            "test_multimodal_once",
            "这是什么？",
            image_urls=("https://cdn.example.test/image.jpg",),
        )
        await chat.chat("test_multimodal_once", "再说详细一点")

        first_messages = client.requests[0][1]["json"]["messages"]
        self.assertEqual(
            first_messages[-1],
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "这是什么？"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://cdn.example.test/image.jpg"
                        },
                    },
                ],
            },
        )

        second_messages = client.requests[1][1]["json"]["messages"]
        self.assertEqual(second_messages[0], {"role": "user", "content": "这是什么？"})
        self.assertNotIn("image_url", repr(second_messages))

    async def test_pure_image_uses_default_prompt_and_text_history_marker(self):
        chat = AIChat(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="grok-4.6",
            system_prompt="",
        )
        client = _Client(
            _Response({"choices": [{"message": {"content": "图片描述"}}]})
        )
        chat._client = client

        await chat.chat(
            "test_pure_image",
            "",
            image_urls=("https://cdn.example.test/image.png",),
        )
        await chat.chat("test_pure_image", "继续")

        first_content = client.requests[0][1]["json"]["messages"][-1]["content"]
        self.assertEqual(first_content[0], {"type": "text", "text": "请描述这张图片"})
        second_messages = client.requests[1][1]["json"]["messages"]
        self.assertEqual(
            second_messages[0],
            {"role": "user", "content": "[用户发送了图片]"},
        )
        self.assertNotIn("https://cdn.example.test/image.png", repr(second_messages))
