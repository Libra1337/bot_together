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
