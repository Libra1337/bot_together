import re
from dataclasses import dataclass
from urllib.parse import urlsplit

GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"
GROUP_MESSAGE_CREATE = "GROUP_MESSAGE_CREATE"
C2C_MESSAGE_CREATE = "C2C_MESSAGE_CREATE"

GROUP_AT_MESSAGE_EVENTS = {GROUP_AT_MESSAGE_CREATE}
GROUP_FULL_MESSAGE_EVENTS = {GROUP_MESSAGE_CREATE}
GROUP_MESSAGE_EVENTS = GROUP_AT_MESSAGE_EVENTS | GROUP_FULL_MESSAGE_EVENTS
MAX_IMAGE_ATTACHMENTS = 4

_LEADING_GROUP_MENTION_RE = re.compile(
    r'^(?:\s*(?:<at\b[^>]*\/>|<@!?[^>\s]+>|@\S+)\s*)+'
)


@dataclass(frozen=True)
class MessageEvent:
    type: str
    group_openid: str
    user_openid: str
    msg_id: str
    content: str
    raw_content: str
    event_type: str
    is_at: bool = False
    is_full_message: bool = False
    limit_user_id: str = ""
    image_urls: tuple[str, ...] = ()

    def to_ctx(self) -> dict[str, object]:
        ctx: dict[str, object] = {
            "type": self.type,
            "group_openid": self.group_openid,
            "user_openid": self.user_openid,
            "limit_user_id": self.limit_user_id or self.user_openid,
            "msg_id": self.msg_id,
        }
        if self.image_urls:
            ctx["image_urls"] = self.image_urls
        return ctx


def normalize_group_content(content: str) -> str:
    return _LEADING_GROUP_MENTION_RE.sub("", content or "").strip()


def _extract_image_urls(data: dict) -> tuple[str, ...]:
    attachments = data.get("attachments", [])
    if not isinstance(attachments, list):
        return ()

    image_urls = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        content_type = str(attachment.get("content_type") or "").lower()
        url = attachment.get("url")
        if not content_type.startswith("image/") or not isinstance(url, str):
            continue

        url = url.strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        image_urls.append(url)
        if len(image_urls) >= MAX_IMAGE_ATTACHMENTS:
            break
    return tuple(image_urls)


def adapt_message_event(
    event_type: str, data: dict, full_message_group_ids: set[str]
) -> MessageEvent | None:
    if event_type in GROUP_MESSAGE_EVENTS:
        group_openid = data.get("group_openid", "")
        is_at = event_type in GROUP_AT_MESSAGE_EVENTS
        is_full_message = event_type in GROUP_FULL_MESSAGE_EVENTS

        if is_full_message and group_openid not in full_message_group_ids:
            return None

        raw_content = data.get("content", "").strip()
        author = data.get("author", {})
        member_openid = author.get("member_openid", "")
        limit_user_id = (
            author.get("user_openid")
            or author.get("union_openid")
            or author.get("union_user_account")
            or member_openid
        )
        return MessageEvent(
            type="group",
            group_openid=group_openid,
            user_openid=member_openid,
            msg_id=data.get("id", ""),
            content=normalize_group_content(raw_content),
            raw_content=raw_content,
            event_type=event_type,
            is_at=is_at,
            is_full_message=is_full_message,
            limit_user_id=limit_user_id,
            image_urls=_extract_image_urls(data),
        )

    if event_type == C2C_MESSAGE_CREATE:
        raw_content = data.get("content", "").strip()
        author = data.get("author", {})
        user_openid = author.get("user_openid", "")
        return MessageEvent(
            type="c2c",
            group_openid="",
            user_openid=user_openid,
            msg_id=data.get("id", ""),
            content=raw_content,
            raw_content=raw_content,
            event_type=event_type,
            limit_user_id=user_openid,
            image_urls=_extract_image_urls(data),
        )

    return None
