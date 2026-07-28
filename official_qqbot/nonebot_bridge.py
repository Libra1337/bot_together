from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, ClassVar

import httpx
import yaml
from nonebot.adapters.qq import Event as QQEvent
from nonebot.adapters.qq.models import GroupMemberAuthor

from adapters.nonebot_bridge import (
    build_qq_bots,
    env_bool,
    event_to_bridge_payload,
    full_message_group_ids,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.yaml")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [NoneBotBridge] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nonebot-bridge")


def _load_config() -> dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _config_value(section: dict[str, Any], key: str, env_name: str, default: str = "") -> str:
    value = os.environ.get(env_name)
    if value is not None and value.strip():
        return value.strip()
    return str(section.get(key, default) or "").strip()


def _configure_nonebot() -> tuple[str, str, set[str]]:
    config = _load_config()
    bot_config = config.get("bot", {})
    bridge_config = config.get("bridge", {})

    app_id = _config_value(bot_config, "app_id", "QQ_APP_ID")
    app_secret = _config_value(bot_config, "app_secret", "QQ_APP_SECRET")
    bot_token = _config_value(bot_config, "token", "QQ_BOT_TOKEN")
    endpoint = _config_value(
        bridge_config,
        "endpoint",
        "PY_BRIDGE_ENDPOINT",
        "http://127.0.0.1:8765/koishi/message",
    )
    token = _config_value(bridge_config, "token", "PY_BRIDGE_TOKEN", "")

    if not app_id or not app_secret:
        raise RuntimeError("QQ_APP_ID and QQ_APP_SECRET are required")

    import nonebot
    from nonebot.adapters.qq import Adapter as QQAdapter

    driver_name = os.environ.get("NONEBOT_DRIVER", "~httpx+~websockets")
    use_websocket = env_bool("NONEBOT_QQ_USE_WEBSOCKET", True)
    qq_bots = build_qq_bots(app_id, bot_token, app_secret, use_websocket)

    nonebot.init(
        driver=driver_name,
        qq_bots=qq_bots,
        qq_is_sandbox=bool(bot_config.get("sandbox", False)),
    )
    nonebot.get_driver().register_adapter(QQAdapter)
    _register_group_message_event()

    return endpoint, token, full_message_group_ids(bot_config)


def _register_group_message_event() -> None:
    try:
        from nonebot.adapters.qq.event import EVENT_CLASSES, QQMessageEvent
    except Exception as error:
        log.warning("failed to register GROUP_MESSAGE_CREATE event: %s", error)
        return

    if "GROUP_MESSAGE_CREATE" in EVENT_CLASSES:
        return

    class GroupMessageCreateEvent(QQMessageEvent):
        __type__: ClassVar[str] = "GROUP_MESSAGE_CREATE"
        author: GroupMemberAuthor
        group_openid: str
        to_me: bool = False

        def get_user_id(self) -> str:
            return self.author.member_openid

        def get_session_id(self) -> str:
            return f"group_{self.group_openid}_{self.author.member_openid}"

    EVENT_CLASSES["GROUP_MESSAGE_CREATE"] = GroupMessageCreateEvent


async def _forward_payload(endpoint: str, token: str, payload: dict[str, Any]) -> None:
    headers = {"content-type": "application/json"}
    if token:
        headers["x-bridge-token"] = token

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
    if response.status_code >= 400:
        log.warning("Python bridge returned %s: %s", response.status_code, response.text[:200])


def main() -> None:
    endpoint, token, group_ids = _configure_nonebot()

    import nonebot
    from nonebot import on_message

    matcher = on_message(priority=1, block=False)

    @matcher.handle()
    async def handle_event(event: QQEvent) -> None:
        payload = event_to_bridge_payload(event, group_ids)
        if not payload:
            return
        log.info(
            "forwarding event=%s group=%s msg=%s",
            payload.get("event_type", ""),
            payload.get("group_openid", ""),
            payload.get("msg_id", ""),
        )
        await _forward_payload(endpoint, token, payload)

    log.info("starting NoneBot QQ bridge, endpoint=%s", endpoint)
    nonebot.run()


if __name__ == "__main__":
    main()
