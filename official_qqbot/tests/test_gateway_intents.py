import unittest

import bot


class GatewayIntentTests(unittest.TestCase):
    def test_default_intents_follow_official_group_and_c2c_event_intent(self):
        expected = 1 << 25

        self.assertEqual(bot.GATEWAY_INTENTS, expected)


if __name__ == "__main__":
    unittest.main()
