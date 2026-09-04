import os
import unittest

import bot


class ConfigEnvTests(unittest.TestCase):
    def test_env_value_overrides_config_value(self):
        old_value = os.environ.get("QQ_APP_SECRET")
        os.environ["QQ_APP_SECRET"] = "env-secret"
        try:
            self.assertEqual(
                bot._config_value({"app_secret": "config-secret"}, "app_secret", "QQ_APP_SECRET"),
                "env-secret",
            )
        finally:
            if old_value is None:
                os.environ.pop("QQ_APP_SECRET", None)
            else:
                os.environ["QQ_APP_SECRET"] = old_value

    def test_config_value_used_when_env_is_absent(self):
        old_value = os.environ.pop("QQ_APP_SECRET", None)
        try:
            self.assertEqual(
                bot._config_value({"app_secret": "config-secret"}, "app_secret", "QQ_APP_SECRET"),
                "config-secret",
            )
        finally:
            if old_value is not None:
                os.environ["QQ_APP_SECRET"] = old_value

    def test_ai_config_value_prefers_dashboard_config_over_environment(self):
        old_value = os.environ.get("AI_MODEL")
        os.environ["AI_MODEL"] = "env-model"
        try:
            self.assertEqual(
                bot._ai_config_value(
                    {"model": "dashboard-model"},
                    "model",
                    "AI_MODEL",
                    "default-model",
                ),
                "dashboard-model",
            )
        finally:
            if old_value is None:
                os.environ.pop("AI_MODEL", None)
            else:
                os.environ["AI_MODEL"] = old_value

    def test_image_ai_config_value_prefers_dashboard_config_over_environment(self):
        old_value = os.environ.get("IMAGE_AI_MODEL")
        os.environ["IMAGE_AI_MODEL"] = "env-image-model"
        try:
            self.assertEqual(
                bot._ai_config_value(
                    {"model": "dashboard-image-model"},
                    "model",
                    "IMAGE_AI_MODEL",
                    "default-image-model",
                ),
                "dashboard-image-model",
            )
        finally:
            if old_value is None:
                os.environ.pop("IMAGE_AI_MODEL", None)
            else:
                os.environ["IMAGE_AI_MODEL"] = old_value

    def test_image_ai_config_value_falls_back_to_environment(self):
        old_value = os.environ.get("IMAGE_AI_MODEL")
        os.environ["IMAGE_AI_MODEL"] = "env-image-model"
        try:
            self.assertEqual(
                bot._ai_config_value(
                    {}, "model", "IMAGE_AI_MODEL", "default-image-model"
                ),
                "env-image-model",
            )
        finally:
            if old_value is None:
                os.environ.pop("IMAGE_AI_MODEL", None)
            else:
                os.environ["IMAGE_AI_MODEL"] = old_value

    def test_ai_config_value_treats_non_mapping_section_as_empty(self):
        self.assertEqual(
            bot._ai_config_value(
                "invalid-section", "model", None, "default-image-model"
            ),
            "default-image-model",
        )

    def test_bool_env_zero_overrides_config_true(self):
        old_value = os.environ.get("QQ_OFFICIAL_WS_ENABLED")
        os.environ["QQ_OFFICIAL_WS_ENABLED"] = "0"
        try:
            self.assertFalse(
                bot._config_bool({"official_ws_enabled": True}, "official_ws_enabled", "QQ_OFFICIAL_WS_ENABLED", True)
            )
        finally:
            if old_value is None:
                os.environ.pop("QQ_OFFICIAL_WS_ENABLED", None)
            else:
                os.environ["QQ_OFFICIAL_WS_ENABLED"] = old_value

    def test_bool_config_used_when_env_is_absent(self):
        old_value = os.environ.pop("QQ_OFFICIAL_WS_ENABLED", None)
        try:
            self.assertFalse(
                bot._config_bool({"official_ws_enabled": False}, "official_ws_enabled", "QQ_OFFICIAL_WS_ENABLED", True)
            )
        finally:
            if old_value is not None:
                os.environ["QQ_OFFICIAL_WS_ENABLED"] = old_value

    def test_full_message_group_ids_include_env_whitelist(self):
        old_value = os.environ.get("QQ_GROUP_WHITELIST")
        os.environ["QQ_GROUP_WHITELIST"] = "group-openid-1, group-openid-2"
        try:
            self.assertEqual(
                bot._full_message_group_ids(
                    {
                        "full_message_group_ids": ["config-group"],
                        "non_at_group_whitelist": ["legacy-group"],
                    }
                ),
                {"config-group", "legacy-group", "group-openid-1", "group-openid-2"},
            )
        finally:
            if old_value is None:
                os.environ.pop("QQ_GROUP_WHITELIST", None)
            else:
                os.environ["QQ_GROUP_WHITELIST"] = old_value


if __name__ == "__main__":
    unittest.main()
