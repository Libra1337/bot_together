import unittest

import httpx

from handlers.image_gen import (
    ImageGenerator,
    extract_image_prompt,
    is_image_request,
)


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _CaptureClient:
    response = _Response()
    calls = []
    error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.__class__.calls.append(
            {"url": url, "headers": headers, "json": json, "client": self.kwargs}
        )
        if self.__class__.error:
            raise self.__class__.error
        return self.__class__.response


class ImagePromptTests(unittest.TestCase):
    def test_explicit_command_extracts_prompt(self):
        self.assertTrue(is_image_request("/生图 一只戴围巾的猫"))
        self.assertEqual(extract_image_prompt("/生图 一只戴围巾的猫"), "一只戴围巾的猫")

    def test_natural_language_extracts_prompt(self):
        self.assertTrue(is_image_request("帮我画一张雨夜里的重庆"))
        self.assertEqual(extract_image_prompt("帮我画一张雨夜里的重庆"), "雨夜里的重庆")

    def test_ordinary_chat_is_not_image_request(self):
        self.assertFalse(is_image_request("你觉得这张图片怎么样"))
        self.assertFalse(is_image_request("今天的美术课学习画图"))

    def test_empty_explicit_command_has_no_prompt(self):
        self.assertTrue(is_image_request("/生图"))
        self.assertEqual(extract_image_prompt("/生图"), "")


class ImageGeneratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _CaptureClient.calls = []
        _CaptureClient.error = None
        _CaptureClient.response = _Response()
        self.generator = ImageGenerator(
            base_url="https://images.example.test/v1/",
            api_key="sk-secret",
            model="grok-imagine",
            size="1024x1024",
            client_factory=_CaptureClient,
        )

    async def test_generate_accepts_url_response_and_sends_openai_payload(self):
        _CaptureClient.response = _Response(
            payload={"data": [{"url": "https://cdn.example.test/result.png"}]}
        )

        result, error = await self.generator.generate("蓝色星空")

        self.assertEqual(error, "")
        self.assertEqual(result.url, "https://cdn.example.test/result.png")
        self.assertEqual(result.b64_json, "")
        call = _CaptureClient.calls[0]
        self.assertEqual(
            call["url"], "https://images.example.test/v1/images/generations"
        )
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-secret")
        self.assertEqual(
            call["json"],
            {
                "model": "grok-imagine",
                "prompt": "蓝色星空",
                "n": 1,
                "size": "1024x1024",
            },
        )

    async def test_generate_accepts_base64_response(self):
        _CaptureClient.response = _Response(payload={"data": [{"b64_json": "YWJj"}]})

        result, error = await self.generator.generate("极简图标")

        self.assertEqual(error, "")
        self.assertEqual(result.url, "")
        self.assertEqual(result.b64_json, "YWJj")

    async def test_generate_rejects_non_http_image_url(self):
        _CaptureClient.response = _Response(
            payload={"data": [{"url": "file:///tmp/generated.png"}]}
        )

        result, error = await self.generator.generate("测试")

        self.assertIsNone(result)
        self.assertEqual(error, "生图接口返回了无效的图片地址")

    async def test_generate_reports_timeout_without_response_content(self):
        request = httpx.Request("POST", "https://images.example.test")
        _CaptureClient.error = httpx.ReadTimeout("slow", request=request)

        result, error = await self.generator.generate("慢速图片")

        self.assertIsNone(result)
        self.assertEqual(error, "生图服务响应超时，请稍后再试")

    async def test_generate_reports_http_status_without_exposing_body(self):
        _CaptureClient.response = _Response(
            status_code=500,
            payload={"error": {"message": "secret upstream details"}},
        )

        result, error = await self.generator.generate("测试")

        self.assertIsNone(result)
        self.assertEqual(error, "生图 API 返回 HTTP 500")
        self.assertNotIn("secret upstream details", error)

    async def test_generate_reports_missing_image(self):
        _CaptureClient.response = _Response(payload={"data": [{}]})

        result, error = await self.generator.generate("测试")

        self.assertIsNone(result)
        self.assertEqual(error, "生图接口返回中没有图片")

    async def test_generate_rejects_incomplete_configuration_without_request(self):
        generator = ImageGenerator(
            base_url="",
            api_key="",
            model="",
            size="1024x1024",
            client_factory=_CaptureClient,
        )

        result, error = await generator.generate("测试")

        self.assertIsNone(result)
        self.assertEqual(error, "AI 生图尚未配置，请联系管理员")
        self.assertEqual(_CaptureClient.calls, [])


if __name__ == "__main__":
    unittest.main()
