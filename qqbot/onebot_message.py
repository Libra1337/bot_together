"""OneBot message helpers."""

import re


def is_at_me(message, bot_qq: int) -> bool:
    """检查消息中是否 @ 了机器人"""
    if isinstance(message, list):
        for seg in message:
            if seg.get("type") == "at":
                qq = seg.get("data", {}).get("qq", "")
                if str(qq) == str(bot_qq):
                    return True
    return False


def extract_text(message) -> str:
    """从 OneBot 消息中提取纯文本内容"""
    if isinstance(message, str):
        return message.strip()

    if isinstance(message, list):
        texts = []
        for seg in message:
            if seg.get("type") == "text":
                texts.append(seg.get("data", {}).get("text", ""))
        return "".join(texts).strip()

    return str(message).strip()


def extract_at_qq(raw_message, bot_qq: int) -> int | None:
    """提取 @某人的 QQ 号（排除 @Bot 自身）"""
    if isinstance(raw_message, list):
        for seg in raw_message:
            if seg.get("type") == "at":
                qq = seg.get("data", {}).get("qq", "")
                if qq and str(qq) != str(bot_qq):
                    return int(qq)
    elif isinstance(raw_message, str):
        match = re.search(r"\[CQ:at,qq=(\d+)\]", raw_message)
        if match and match.group(1) != str(bot_qq):
            return int(match.group(1))
    return None
