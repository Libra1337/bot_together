import unittest

from adapters.qq_official import (
    GROUP_AT_MESSAGE_CREATE,
    GROUP_MESSAGE_CREATE,
    C2C_MESSAGE_CREATE,
    adapt_message_event,
)


class QQOfficialAdapterTests(unittest.TestCase):
    def test_whitelisted_full_group_message_does_not_require_mention(self):
        event = adapt_message_event(
            GROUP_MESSAGE_CREATE,
            {
                "group_openid": "1097445697",
                "id": "msg-full",
                "author": {
                    "member_openid": "member-openid",
                    "user_openid": "global-user-openid",
                },
                "content": "hello",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, "group")
        self.assertEqual(event.group_openid, "1097445697")
        self.assertEqual(event.user_openid, "member-openid")
        self.assertEqual(event.limit_user_id, "global-user-openid")
        self.assertEqual(event.to_ctx()["limit_user_id"], "global-user-openid")
        self.assertEqual(event.msg_id, "msg-full")
        self.assertEqual(event.content, "hello")
        self.assertEqual(event.raw_content, "hello")
        self.assertFalse(event.is_at)
        self.assertTrue(event.is_full_message)

    def test_non_whitelisted_full_group_message_is_ignored(self):
        event = adapt_message_event(
            GROUP_MESSAGE_CREATE,
            {
                "group_openid": "other-group",
                "id": "msg-other",
                "author": {"member_openid": "user-openid"},
                "content": "hello",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNone(event)

    def test_at_group_message_is_allowed_outside_whitelist_and_strips_mention(self):
        event = adapt_message_event(
            GROUP_AT_MESSAGE_CREATE,
            {
                "group_openid": "other-group",
                "id": "msg-at",
                "author": {"member_openid": "user-openid"},
                "content": "<@!1903707124> /help",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.content, "/help")
        self.assertTrue(event.is_at)
        self.assertFalse(event.is_full_message)

    def test_c2c_message_passes_through_without_stripping_at_text(self):
        event = adapt_message_event(
            C2C_MESSAGE_CREATE,
            {
                "id": "msg-c2c",
                "author": {"user_openid": "user-openid"},
                "content": "@bot hello",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, "c2c")
        self.assertEqual(event.content, "@bot hello")
        self.assertEqual(event.user_openid, "user-openid")


if __name__ == "__main__":
    unittest.main()
