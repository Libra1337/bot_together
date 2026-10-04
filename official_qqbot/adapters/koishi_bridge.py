from adapters.qq_official import (
    GROUP_AT_MESSAGE_CREATE,
    GROUP_MESSAGE_CREATE,
    MessageEvent,
    normalize_group_content,
)


def _first_string(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def adapt_koishi_payload(
    payload: dict, full_message_group_ids: set[str]
) -> MessageEvent | None:
    event_type = _first_string(payload, "event_type") or "KOISHI_MESSAGE"
    message_type = _first_string(payload, "type", "message_type")
    group_openid = _first_string(payload, "group_openid", "guild_id", "guildId")
    user_openid = _first_string(payload, "user_openid", "user_id", "userId")
    limit_user_id = _first_string(
        payload,
        "limit_user_id",
        "global_user_openid",
        "global_user_id",
        "user_openid",
        "user_id",
        "userId",
    )
    msg_id = _first_string(payload, "msg_id", "message_id", "messageId", "id")
    raw_content = _first_string(payload, "raw_content", "content")
    is_at = bool(payload.get("is_at")) or event_type == GROUP_AT_MESSAGE_CREATE

    if message_type == "c2c" or (not group_openid and user_openid):
        return MessageEvent(
            type="c2c",
            group_openid="",
            user_openid=user_openid,
            msg_id=msg_id,
            content=raw_content,
            raw_content=raw_content,
            event_type=event_type,
            is_at=is_at,
            is_full_message=False,
            limit_user_id=limit_user_id or user_openid,
        )

    if not is_at and full_message_group_ids and group_openid not in full_message_group_ids:
        return None

    is_full_message = event_type == GROUP_MESSAGE_CREATE or not is_at

    return MessageEvent(
        type="group",
        group_openid=group_openid,
        user_openid=user_openid,
        msg_id=msg_id,
        content=normalize_group_content(raw_content) if is_at else raw_content,
        raw_content=raw_content,
        event_type=event_type,
        is_at=is_at,
        is_full_message=is_full_message,
        limit_user_id=limit_user_id or user_openid,
    )
