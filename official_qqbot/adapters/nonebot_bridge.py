from __future__ import annotations

import os
from typing import Any

from adapters.qq_official import (
    C2C_MESSAGE_CREATE,
    GROUP_AT_MESSAGE_CREATE,
    GROUP_MESSAGE_CREATE,
    normalize_group_content,
)


def build_qq_bots(
    app_id: str, token: str, secret: str, use_websocket: bool = True
) -> list[dict[str, Any]]:
    return [
        {
            "id": app_id,
            "token": token,
            "secret": secret,
            "intent": {
                "c2c_group_at_messages": True,
                "at_messages": False,
                "guild_messages": False,
            },
            "use_websocket": use_websocket,
        }
    ]


def env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def env_string_set(name: str) -> set[str]:
    return {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}


def string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not value:
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def full_message_group_ids(section: dict[str, Any]) -> set[str]:
    return (
        string_set(section.get("full_message_group_ids", []))
        | string_set(section.get("non_at_group_whitelist", []))
        | env_string_set("QQ_GROUP_WHITELIST")
    )


def event_to_bridge_payload(
    event: Any, full_message_group_ids: set[str]
) -> dict[str, Any] | None:
    event_type = _event_type(event)

    if event_type == C2C_MESSAGE_CREATE:
        content = _event_plain_text(event)
        msg_id = _first_non_empty(
            getattr(event, "id", ""),
            getattr(event, "event_id", ""),
        )
        return {
            "type": "c2c",
            "group_openid": "",
            "user_openid": _author_openid(event, "user_openid", "id"),
            "msg_id": msg_id,
            "content": content,
            "raw_content": content,
            "is_at": False,
            "event_type": event_type,
            "source": "nonebot-adapter-qq",
        }

    if event_type in {GROUP_AT_MESSAGE_CREATE, GROUP_MESSAGE_CREATE}:
        if getattr(getattr(event, "author", None), "bot", False):
            return None
        group_openid = _first_non_empty(getattr(event, "group_openid", ""))
        is_at = event_type == GROUP_AT_MESSAGE_CREATE
        if not is_at and full_message_group_ids and group_openid not in full_message_group_ids:
            return None

        content = _event_plain_text(event)
        msg_id = _first_non_empty(
            getattr(event, "id", ""),
            getattr(event, "event_id", ""),
        )
        return {
            "type": "group",
            "group_openid": group_openid,
            "user_openid": _author_openid(event, "member_openid", "id"),
            "msg_id": msg_id,
            "content": normalize_group_content(content) if is_at else content,
            "raw_content": content,
            "is_at": is_at,
            "event_type": event_type,
            "source": "nonebot-adapter-qq",
        }

    return None


def _event_type(event: Any) -> str:
    get_event_name = getattr(event, "get_event_name", None)
    if callable(get_event_name):
        value = get_event_name()
    else:
        value = getattr(event, "__type__", "")
    return getattr(value, "value", value) or ""


def _event_plain_text(event: Any) -> str:
    get_message = getattr(event, "get_message", None)
    if callable(get_message):
        message = get_message()
        extract_plain_text = getattr(message, "extract_plain_text", None)
        if callable(extract_plain_text):
            return str(extract_plain_text()).strip()
        extract_content = getattr(message, "extract_content", None)
        if callable(extract_content):
            return str(extract_content(False)).strip()
        return str(message).strip()
    return _first_non_empty(getattr(event, "content", ""), getattr(event, "message", ""))


def _author_openid(event: Any, *keys: str) -> str:
    author = getattr(event, "author", None)
    if author is None:
        return ""
    for key in keys:
        value = getattr(author, key, "")
        if value:
            return str(value).strip()
    return ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
