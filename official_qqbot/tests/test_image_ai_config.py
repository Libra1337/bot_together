import tempfile
import unittest
from pathlib import Path

import yaml

from control_api.image_ai_config import ImageAIConfigManager, ImageAISettings


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _Client:
    response = _Response()
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.__class__.calls.append({"url": url, "headers": headers, "json": json})
        return self.__class__.response


class ImageAIConfigManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "bot": {"app_id": "app-1"},
                    "ai": {
                        "base_url": "https://chat.example.test/v1",
                        "api_key": "chat-secret",
                        "model": "chat-model",
                    },
                    "image_ai": {
                        "enabled": True,
                        "base_url": "https://image.example.test/v1",
                        "api_key": "sk-image-secret",
                        "model": "image-model",
                        "size": "1024x1024",
                        "cooldown_seconds": 60,
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        _Client.calls = []
        _Client.response = _Response(
            payload={"data": [{"url": "https://cdn.example.test/preview.png"}]}
        )
        self.manager = ImageAIConfigManager(
            self.config_path,
            client_factory=_Client,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_public_settings_mask_image_key(self):
        settings = self.manager.load()
        public = self.manager.public_settings()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.base_url, "https://image.example.test/v1")
        self.assertEqual(settings.model, "image-model")
        self.assertEqual(settings.api_key, "sk-image-secret")
        self.assertEqual(settings.size, "1024x1024")
        self.assertEqual(settings.cooldown_seconds, 60)
        self.assertEqual(public["api_key_masked"], "sk-***cret")
        self.assertNotIn("sk-image-secret", str(public))

    def test_load_uses_disabled_defaults_when_section_is_missing(self):
        self.config_path.write_text("bot:\n  app_id: app-1\n", encoding="utf-8")

        settings = self.manager.load()

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.base_url, "")
        self.assertEqual(settings.model, "grok-imagine-1.0-fast")
        self.assertEqual(settings.size, "1024x1024")
        self.assertEqual(settings.cooldown_seconds, 60)

    def test_validate_rejects_invalid_fields(self):
        valid = ImageAISettings(
            enabled=True,
            base_url="https://image.example.test/v1",
            model="image-model",
            api_key="secret",
            size="1024x1024",
            cooldown_seconds=60,
        )

        self.assertIsNone(self.manager.validate(valid))
        self.assertIn("API 地址", self.manager.validate(valid.__class__(True, "bad", "m", "k", "1024x1024", 60)))
        self.assertIn("模型", self.manager.validate(valid.__class__(True, valid.base_url, "", "k", "1024x1024", 60)))
        self.assertIn("API Key", self.manager.validate(valid.__class__(True, valid.base_url, "m", "", "1024x1024", 60)))
        self.assertIn("图片尺寸", self.manager.validate(valid.__class__(True, valid.base_url, "m", "k", "800x800", 60)))
        self.assertIn("冷却", self.manager.validate(valid.__class__(True, valid.base_url, "m", "k", "1024x1024", 86401)))

    async def test_check_returns_url_preview_without_saving(self):
        settings = self.manager.load()
        before = self.config_path.read_bytes()

        ok, message, image = await self.manager.check(settings)

        self.assertTrue(ok)
        self.assertEqual(message, "生图连接成功")
        self.assertEqual(image.url, "https://cdn.example.test/preview.png")
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(
            _Client.calls[0]["url"],
            "https://image.example.test/v1/images/generations",
        )

    async def test_check_returns_base64_preview(self):
        _Client.response = _Response(payload={"data": [{"b64_json": "YWJj"}]})

        ok, message, image = await self.manager.check(self.manager.load())

        self.assertTrue(ok)
        self.assertEqual(message, "生图连接成功")
        self.assertEqual(image.b64_json, "YWJj")

    async def test_check_rejects_disabled_or_invalid_settings(self):
        settings = ImageAISettings(False, "", "", "", "1024x1024", 60)

        ok, message, image = await self.manager.check(settings)

        self.assertFalse(ok)
        self.assertIn("API 地址", message)
        self.assertIsNone(image)
        self.assertEqual(_Client.calls, [])

    def test_save_preserves_chat_ai_and_other_sections(self):
        settings = ImageAISettings(
            enabled=True,
            base_url="https://new-image.example.test/v1",
            model="new-image-model",
            api_key="new-image-key",
            size="1536x1024",
            cooldown_seconds=90,
        )

        snapshot = self.manager.save(settings)
        payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

        self.assertIn(b"chat-secret", snapshot)
        self.assertEqual(payload["bot"], {"app_id": "app-1"})
        self.assertEqual(payload["ai"]["api_key"], "chat-secret")
        self.assertEqual(
            payload["image_ai"],
            {
                "enabled": True,
                "base_url": "https://new-image.example.test/v1",
                "api_key": "new-image-key",
                "model": "new-image-model",
                "size": "1536x1024",
                "cooldown_seconds": 90,
            },
        )

    def test_restore_reinstates_snapshot(self):
        snapshot = self.config_path.read_bytes()
        self.manager.save(
            ImageAISettings(
                True,
                "https://new.example.test/v1",
                "new-model",
                "new-key",
                "1024x1024",
                10,
            )
        )

        self.manager.restore(snapshot)

        self.assertEqual(self.config_path.read_bytes(), snapshot)

    def test_restart_bot_reports_active_service(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            stdout = "active\n" if "is-active" in command else ""
            return type("Result", (), {"returncode": 0, "stdout": stdout})()

        manager = ImageAIConfigManager(self.config_path, command_runner=runner)

        ok, message = manager.restart_bot()

        self.assertTrue(ok)
        self.assertEqual(message, "Bot 已重启并使用新配置")
        self.assertEqual(calls[0], ["systemctl", "restart", "official-qqbot"])


if __name__ == "__main__":
    unittest.main()
