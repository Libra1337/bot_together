import unittest

from adapters.nonebot_bridge import (
    build_qq_bots,
    event_to_bridge_payload,
    full_message_group_ids,
)


class FakeMessage:
    def __init__(self, text):
        self.text = text

    def extract_plain_text(self):
        return self.text


class FakeAuthor:
    def __init__(self, user_openid="", member_openid="", id=""):
        self.user_openid = user_openid
        self.member_openid = member_openid
        self.id = id


class FakeEvent:
    def __init__(self, event_type, message, **attrs):
        self.__type__ = event_type
        self.event_id = attrs.pop("event_id", "")
        self.id = attrs.pop("id", "")
        self.author = attrs.pop("author", FakeAuthor())
        for key, value in attrs.items():
            setattr(self, key, value)
        self._message = FakeMessage(message)

    def get_event_name(self):
        return self.__type__

    def get_message(self):
        return self._message


class NonMessageEvent:
    def get_event_name(self):
        return "READY"

    def get_message(self):
        raise ValueError("Event has no message!")


class NoneBotBridgeAdapterTests(unittest.TestCase):
    def test_full_message_group_ids_include_config_and_env(self):
        import os

        old_value = os.environ.get("QQ_GROUP_WHITELIST")
        os.environ["QQ_GROUP_WHITELIST"] = "env-group"
        try:
            groups = full_message_group_ids(
                {
                    "full_message_group_ids": ["config-group"],
                    "non_at_group_whitelist": "legacy-group",
                }
            )
        finally:
            if old_value is None:
                os.environ.pop("QQ_GROUP_WHITELIST", None)
            else:
                os.environ["QQ_GROUP_WHITELIST"] = old_value

        self.assertEqual(groups, {"config-group", "legacy-group", "env-group"})

    def test_build_qq_bots_enables_group_and_c2c_intent(self):
        bots = build_qq_bots("app-id", "bot-token", "secret", use_websocket=True)

        self.assertEqual(
            bots,
            [
                {
                    "id": "app-id",
                    "token": "bot-token",
                    "secret": "secret",
                    "intent": {
                        "c2c_group_at_messages": True,
                        "at_messages": False,
                        "guild_messages": False,
                    },
                    "use_websocket": True,
                }
            ],
        )

    def test_group_at_event_is_forwarded_without_whitelist(self):
        event = FakeEvent(
            "GROUP_AT_MESSAGE_CREATE",
            "<@!1903707124> menu",
            id="msg-at",
            group_openid="outside-full-group",
            author=FakeAuthor(member_openid="member-openid"),
        )

        payload = event_to_bridge_payload(event, full_message_group_ids={"full-group"})

        self.assertEqual(payload["type"], "group")
        self.assertEqual(payload["group_openid"], "outside-full-group")
        self.assertEqual(payload["user_openid"], "member-openid")
        self.assertEqual(payload["msg_id"], "msg-at")
        self.assertEqual(payload["content"], "menu")
        self.assertTrue(payload["is_at"])
        self.assertEqual(payload["event_type"], "GROUP_AT_MESSAGE_CREATE")

    def test_c2c_event_is_forwarded(self):
        event = FakeEvent(
            "C2C_MESSAGE_CREATE",
            "menu",
            id="msg-c2c",
            author=FakeAuthor(user_openid="user-openid"),
        )

        payload = event_to_bridge_payload(event, full_message_group_ids=set())

        self.assertEqual(payload["type"], "c2c")
        self.assertEqual(payload["group_openid"], "")
        self.assertEqual(payload["user_openid"], "user-openid")
        self.assertEqual(payload["content"], "menu")
        self.assertFalse(payload["is_at"])

    def test_whitelisted_full_group_event_is_forwarded(self):
        event = FakeEvent(
            "GROUP_MESSAGE_CREATE",
            "menu",
            id="msg-full",
            group_openid="full-group",
            author=FakeAuthor(member_openid="member-openid"),
        )

        payload = event_to_bridge_payload(event, full_message_group_ids={"full-group"})

        self.assertEqual(payload["type"], "group")
        self.assertEqual(payload["group_openid"], "full-group")
        self.assertEqual(payload["content"], "menu")
        self.assertFalse(payload["is_at"])
        self.assertEqual(payload["event_type"], "GROUP_MESSAGE_CREATE")

    def test_non_whitelisted_full_group_event_is_ignored(self):
        event = FakeEvent(
            "GROUP_MESSAGE_CREATE",
            "menu",
            id="msg-full",
            group_openid="outside-full-group",
            author=FakeAuthor(member_openid="member-openid"),
        )

        payload = event_to_bridge_payload(event, full_message_group_ids={"full-group"})

        self.assertIsNone(payload)

    def test_non_message_event_is_ignored_without_reading_message(self):
        payload = event_to_bridge_payload(NonMessageEvent(), full_message_group_ids=set())

        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
