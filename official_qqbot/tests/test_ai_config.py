import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import yaml

from control_api.ai_config import AIConfigManager, AISettings


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.post = AsyncMock(side_effect=self._post)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def _post(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


class AIConfigManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "bot": {"app_id": "app-1"},
                    "ai": {
                        "base_url": "https://api.example.test/v1",
                        "api_key": "sk-full-secret",
                        "model": "model-a",
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_masks_key_and_reads_ai_values(self):
        manager = AIConfigManager(self.config_path)

        self.assertEqual(
            manager.public_settings(),
            {
                "base_url": "https://api.example.test/v1",
                "model": "model-a",
                "api_key_configured": True,
                "api_key_masked": "sk-***cret",
            },
        )

    def test_validate_rejects_invalid_url_and_empty_model_or_key(self):
        manager = AIConfigManager(self.config_path)

        self.assertIn(
            "API 地址",
            manager.validate(AISettings("ftp://bad", "m", "k")),
        )
        self.assertIn(
            "模型",
            manager.validate(AISettings("https://api.example.test/v1", "", "k")),
        )
        self.assertIn(
            "Key",
            manager.validate(AISettings("https://api.example.test/v1", "m", "")),
        )

    def test_check_accepts_openai_compatible_response(self):
        response = FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
        manager = AIConfigManager(
            self.config_path,
            client_factory=lambda **kwargs: FakeAsyncClient(response=response),
        )

        result = asyncio.run(
            manager.check(
                AISettings("https://api.example.test/v1", "model-a", "secret")
            )
        )

        self.assertEqual(result, (True, "连接成功"))

    def test_check_rejects_non_success_response_without_exposing_body(self):
        response = FakeResponse(401, {"error": {"message": "secret provider detail"}})
        manager = AIConfigManager(
            self.config_path,
            client_factory=lambda **kwargs: FakeAsyncClient(response=response),
        )

        result = asyncio.run(
            manager.check(
                AISettings("https://api.example.test/v1", "model-a", "secret")
            )
        )

        self.assertEqual(result, (False, "API 返回 HTTP 401"))
        self.assertNotIn("secret provider detail", result[1])

    def test_save_keeps_other_config_sections(self):
        manager = AIConfigManager(self.config_path)
        manager.save(
            AISettings(
                "https://api.example.test/new-v1",
                "model-b",
                "sk-full-secret",
            )
        )

        saved = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["bot"]["app_id"], "app-1")
        self.assertEqual(
            saved["ai"],
            {
                "base_url": "https://api.example.test/new-v1",
                "api_key": "sk-full-secret",
                "model": "model-b",
            },
        )

    def test_restore_returns_previous_config_bytes(self):
        manager = AIConfigManager(self.config_path)
        original = self.config_path.read_bytes()
        snapshot = manager.save(
            AISettings("https://api.example.test/new-v1", "model-b", "new-secret")
        )

        manager.restore(snapshot)

        self.assertEqual(snapshot, original)
        self.assertEqual(self.config_path.read_bytes(), original)

    def test_restart_reports_command_failure(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "failed")

        manager = AIConfigManager(self.config_path, command_runner=runner)

        result = manager.restart_bot()

        self.assertEqual(result, (False, "Bot 重启失败"))


if __name__ == "__main__":
    unittest.main()
