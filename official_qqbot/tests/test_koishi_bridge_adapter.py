import unittest

from adapters.koishi_bridge import adapt_koishi_payload


class KoishiBridgeAdapterTests(unittest.TestCase):
    def test_whitelisted_group_message_without_mention_is_accepted(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "group_openid": "1097445697",
                "user_openid": "user-openid",
                "msg_id": "msg-1",
                "content": "stock",
                "raw_content": "stock",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, "group")
        self.assertEqual(event.group_openid, "1097445697")
        self.assertEqual(event.user_openid, "user-openid")
        self.assertEqual(event.msg_id, "msg-1")
        self.assertEqual(event.content, "stock")
        self.assertFalse(event.is_at)
        self.assertTrue(event.is_full_message)

    def test_group_message_keeps_global_limit_user_id(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "group_openid": "1097445697",
                "user_openid": "member-openid",
                "limit_user_id": "global-user-id",
                "msg_id": "msg-global-limit",
                "content": "/163",
                "raw_content": "/163",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.user_openid, "member-openid")
        self.assertEqual(event.limit_user_id, "global-user-id")
        self.assertEqual(event.to_ctx()["limit_user_id"], "global-user-id")

    def test_non_whitelisted_group_message_is_ignored(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "group_openid": "other-group",
                "user_openid": "user-openid",
                "msg_id": "msg-2",
                "content": "stock",
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNone(event)

    def test_at_group_message_is_accepted_outside_full_message_whitelist(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "event_type": "GROUP_AT_MESSAGE_CREATE",
                "group_openid": "other-group",
                "user_openid": "user-openid",
                "msg_id": "msg-at-1",
                "content": "<@!1903707124> menu",
                "is_at": True,
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, "group")
        self.assertEqual(event.group_openid, "other-group")
        self.assertEqual(event.content, "menu")
        self.assertTrue(event.is_at)
        self.assertFalse(event.is_full_message)

    def test_group_message_strips_leading_mention(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "group_openid": "1097445697",
                "user_openid": "user-openid",
                "msg_id": "msg-3",
                "content": "<@!1903707124> /help",
                "is_at": True,
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.content, "/help")
        self.assertTrue(event.is_at)

    def test_group_message_strips_koishi_at_element_markup(self):
        event = adapt_koishi_payload(
            {
                "type": "group",
                "event_type": "GROUP_AT_MESSAGE_CREATE",
                "group_openid": "other-group",
                "user_openid": "user-openid",
                "msg_id": "msg-koishi-at",
                "content": '<at id="1903707124"/> 菜单',
                "is_at": True,
            },
            full_message_group_ids={"1097445697"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.content, "菜单")
        self.assertTrue(event.is_at)


if __name__ == "__main__":
    unittest.main()
