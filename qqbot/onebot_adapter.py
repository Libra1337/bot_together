"""OneBot / NapCat transport helpers."""

import asyncio
import json
import logging
import uuid

import websockets


class OneBotTransport:
    """Encapsulates OneBot request/response and message sending behavior."""

    def __init__(
        self,
        logger: logging.Logger,
        send_max_retries: int = 3,
        send_retry_delays: list[int] | None = None,
    ):
        self._logger = logger
        self._send_max_retries = send_max_retries
        self._send_retry_delays = send_retry_delays or [1, 2, 4]
        self._pending_api: dict[str, asyncio.Future] = {}
        self._ws_send_lock = asyncio.Lock()

    def is_ws_closed(self, ws) -> bool:
        return bool(getattr(ws, "closed", getattr(ws, "state", 0) == 3))

    @staticmethod
    def _summarize_params(params: dict) -> str:
        if not isinstance(params, dict):
            return "target=?"

        if "user_id" in params:
            return f"user_id={params.get('user_id')}"
        if "group_id" in params:
            return f"group_id={params.get('group_id')}"
        if "flag" in params:
            return f"flag={params.get('flag')}"
        return "target=?"

    def normalize_api_response(self, resp) -> dict:
        if not isinstance(resp, dict):
            return {"retcode": -1, "status": "invalid", "data": resp}

        normalized = dict(resp)
        retcode = normalized.get("retcode")

        if retcode is None:
            normalized["retcode"] = 0 if normalized.get("status") == "ok" else -1
            return normalized

        try:
            normalized["retcode"] = int(retcode)
        except (TypeError, ValueError):
            normalized["retcode"] = -1

        return normalized

    def normalize_incoming_payload(self, payload) -> dict | None:
        if not isinstance(payload, dict):
            return None

        packet_type = payload.get("type")
        packet_data = (
            payload.get("data") if isinstance(payload.get("data"), dict) else None
        )

        if packet_type in {"hello", "ping", "pong", "heartbeat", "keepalive"}:
            return None

        if packet_type == "response":
            return self.normalize_api_response(payload)

        if packet_type == "event":
            if packet_data:
                converted = _convert_bridge_event_to_onebot(packet_data)
                if converted:
                    return converted
                if "post_type" in packet_data or "retcode" in packet_data:
                    return packet_data
            return {
                "post_type": "meta_event",
                "meta_event_type": "bridge_event",
                "sub_type": packet_data.get("eventType", "unknown")
                if packet_data
                else "unknown",
            }

        if packet_type in {"meta", "status", "state", "ready"}:
            return {
                "post_type": "meta_event",
                "meta_event_type": packet_type,
                "sub_type": payload.get("sub_type", payload.get("status", "")),
                **(packet_data or {}),
            }

        if packet_data:
            if "eventType" in packet_data:
                converted = _convert_bridge_event_to_onebot(packet_data)
                if converted:
                    return converted
            if "post_type" in packet_data or "retcode" in packet_data:
                return packet_data
            if "status" in packet_data and (
                "echo" in packet_data or "retcode" in packet_data
            ):
                return self.normalize_api_response(packet_data)

        if "status" in payload and ("echo" in payload or "retcode" in payload):
            return self.normalize_api_response(payload)

        if "post_type" in payload or "retcode" in payload:
            return payload

        if packet_type:
            return {
                "post_type": "meta_event",
                "meta_event_type": "unknown_packet",
                "sub_type": str(packet_type),
                "raw": payload,
            }

        return payload

    def cancel_pending(self):
        for future in list(self._pending_api.values()):
            if not future.done():
                future.cancel()
        self._pending_api.clear()

    def resolve_pending(self, resp: dict | None = None):
        """Resolve pending API futures immediately when the active WS becomes unusable."""
        normalized = self.normalize_api_response(
            resp or {"retcode": -1, "status": "disconnected"}
        )
        for future in list(self._pending_api.values()):
            if not future.done():
                future.set_result(dict(normalized))
        self._pending_api.clear()

    def handle_api_response(self, data: dict) -> bool:
        normalized = self.normalize_api_response(data)
        echo = normalized.get("echo", "")

        if echo and echo in self._pending_api:
            try:
                self._pending_api[echo].set_result(normalized)
            except asyncio.InvalidStateError:
                pass
            return True

        if normalized.get("retcode") not in (0, None):
            retcode = normalized.get("retcode")
            if retcode == 1200:
                self._logger.debug(f"[API响应] 网络异常(1200), echo={echo}")
            else:
                self._logger.warning(f"[API响应] 错误 retcode={retcode}")

        return True

    async def send_raw(
        self, ws, message_type: str, user_id: int, group_id: int, text: str
    ):
        if message_type == "group":
            payload = {
                "action": "send_group_msg",
                "params": {"group_id": group_id, "message": text},
            }
        else:
            payload = {
                "action": "send_private_msg",
                "params": {"user_id": user_id, "message": text},
            }

        try:
            await self._send_json(ws, payload)
        except Exception:
            pass

    async def send_reply(
        self, ws, message_type: str, user_id: int, group_id: int, reply_text: str
    ):
        if message_type == "group":
            await self.send_group_msg(ws, group_id, reply_text)
            return

        await self.send_private_msg(ws, user_id, reply_text)

    async def send_group_msg(self, ws, group_id: int, text: str):
        await self._send_message_action(
            ws, "send_group_msg", {"group_id": group_id, "message": text}
        )

    async def send_private_msg(self, ws, user_id: int, text: str):
        await self._send_message_action(
            ws, "send_private_msg", {"user_id": user_id, "message": text}
        )

    async def send_api_request(
        self, ws, action: str, params: dict, timeout: float = 10
    ) -> dict:
        echo = str(uuid.uuid4())
        payload = {"action": action, "params": params, "echo": echo}
        loop = _get_running_loop()
        future = loop.create_future()
        self._pending_api[echo] = future

        await self._send_json(ws, payload)

        try:
            resp = await asyncio.wait_for(future, timeout=timeout)
            return self.normalize_api_response(resp)
        except asyncio.TimeoutError:
            self._logger.warning(
                f"[API超时] action={action} {self._summarize_params(params)} timeout={timeout}s ws_closed={self.is_ws_closed(ws)}"
            )
            return {"retcode": -1, "status": "timeout"}
        finally:
            self._pending_api.pop(echo, None)

    async def _send_message_action(self, ws, action: str, params: dict) -> bool:
        for attempt in range(self._send_max_retries):
            try:
                resp = await self.send_api_request(ws, action, params, timeout=15)
                retcode = resp.get("retcode", 0)
                if retcode == 0:
                    return True

                if retcode in (1200, -1):
                    delay = self._send_retry_delays[
                        min(attempt, len(self._send_retry_delays) - 1)
                    ]
                    status = resp.get("status", "unknown")
                    self._logger.warning(
                        f"[发送重试] 第 {attempt + 1} 次失败 action={action} {self._summarize_params(params)} "
                        f"(retcode={retcode}, status={status}, ws_closed={self.is_ws_closed(ws)})，{delay}s 后重试"
                    )
                    await asyncio.sleep(delay)
                    continue

                status = resp.get("status", "unknown")
                self._logger.warning(
                    f"[发送失败] action={action} {self._summarize_params(params)} "
                    f"retcode={retcode} status={status} ws_closed={self.is_ws_closed(ws)}, 不重试"
                )
                return False
            except (websockets.exceptions.ConnectionClosed, ConnectionError):
                self._logger.warning(
                    f"[发送重试] WebSocket 已断开，放弃发送 action={action} {self._summarize_params(params)}"
                )
                return False
            except Exception as e:
                self._logger.warning(
                    f"[发送重试] action={action} {self._summarize_params(params)} "
                    f"ws_closed={self.is_ws_closed(ws)} 异常: {e}"
                )
                if attempt < self._send_max_retries - 1:
                    await asyncio.sleep(
                        self._send_retry_delays[
                            min(attempt, len(self._send_retry_delays) - 1)
                        ]
                    )

        self._logger.error(
            f"[发送失败] action={action} {self._summarize_params(params)} 所有重试均失败，消息丢弃"
        )
        return False

    async def _send_json(self, ws, payload: dict):
        if self.is_ws_closed(ws):
            raise ConnectionError("WebSocket is closed")

        async with self._ws_send_lock:
            if self.is_ws_closed(ws):
                raise ConnectionError("WebSocket is closed")
            await ws.send(json.dumps(payload))


def _get_running_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


def _convert_bridge_event_to_onebot(event) -> dict | None:
    if not isinstance(event, dict):
        return None

    event_type = event.get("eventType")

    if event_type == "message":
        data = _extract_extra_data(event)
        sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
        return {
            "post_type": "message",
            "self_id": event.get("selfId", 0),
            "user_id": event.get("userId", 0),
            "group_id": event.get("groupId", 0),
            "message_id": event.get("messageId", ""),
            "message_type": event.get("chatType", "private"),
            "raw_message": event.get("rawText", ""),
            "message": _normalize_bridge_segments(event.get("segments")),
            "time": _normalize_timestamp_to_seconds(event.get("timestamp")),
            "sender": sender,
            **data,
        }

    if event_type == "notice":
        data = _extract_extra_data(event)
        return {
            "post_type": "notice",
            "self_id": event.get("selfId", 0),
            "user_id": event.get("userId", 0),
            "group_id": event.get("groupId", 0),
            "operator_id": event.get("operatorId", 0),
            "message_id": event.get("messageId", ""),
            "notice_type": event.get("noticeType", "unknown"),
            "sub_type": event.get("subType", ""),
            "time": _normalize_timestamp_to_seconds(event.get("timestamp")),
            **data,
        }

    if event_type == "request":
        data = _extract_extra_data(event)
        return {
            "post_type": "request",
            "self_id": event.get("selfId", 0),
            "user_id": event.get("userId", 0),
            "group_id": event.get("groupId", 0),
            "request_type": event.get("requestType", "unknown"),
            "sub_type": event.get("subType", ""),
            "flag": event.get("flag", ""),
            "comment": event.get("comment", ""),
            "time": _normalize_timestamp_to_seconds(event.get("timestamp")),
            **data,
        }

    if event_type == "meta":
        data = _extract_extra_data(event)
        return {
            "post_type": "meta_event",
            "self_id": event.get("selfId", 0),
            "meta_event_type": event.get("metaEventType", "lifecycle"),
            "sub_type": event.get("subType", ""),
            "time": _normalize_timestamp_to_seconds(event.get("timestamp")),
            **data,
        }

    return {
        "post_type": "meta_event",
        "self_id": event.get("selfId", 0),
        "meta_event_type": "unknown_bridge_event",
        "sub_type": str(event_type or "unknown"),
        **_extract_extra_data(event),
    }


def _extract_extra_data(event: dict) -> dict:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _normalize_bridge_segments(segments) -> list:
    if not isinstance(segments, list):
        return []

    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue

        seg_type = segment.get("type")
        if not isinstance(seg_type, str):
            continue

        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        normalized.append({"type": seg_type, "data": data})

    return normalized


def _normalize_timestamp_to_seconds(value) -> int:
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 1_000_000_000_000 else int(value)

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0

    return int(parsed / 1000) if parsed > 1_000_000_000_000 else parsed
