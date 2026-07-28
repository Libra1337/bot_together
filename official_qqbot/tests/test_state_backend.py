import unittest

from state_backend import build_state_backend


class StateBackendTests(unittest.TestCase):
    def test_local_backend_is_default_without_control_api_url(self):
        backend = build_state_backend(control_api_base_url="", bot_token="")
        self.assertEqual(backend.backend_name, "local")

    def test_cloud_backend_is_selected_with_control_api_url(self):
        backend = build_state_backend(
            control_api_base_url="http://control",
            bot_token="bot-token",
        )
        self.assertEqual(backend.backend_name, "cloud")


if __name__ == "__main__":
    unittest.main()
