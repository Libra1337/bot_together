import unittest

import bot


class KoishiBridgeHttpTests(unittest.TestCase):
    def test_empty_bridge_token_accepts_any_token(self):
        self.assertTrue(bot._bridge_token_matches("", ""))
        self.assertTrue(bot._bridge_token_matches("", "anything"))

    def test_configured_bridge_token_must_match(self):
        self.assertTrue(bot._bridge_token_matches("secret", "secret"))
        self.assertFalse(bot._bridge_token_matches("secret", "wrong"))
        self.assertFalse(bot._bridge_token_matches("secret", ""))


if __name__ == "__main__":
    unittest.main()
