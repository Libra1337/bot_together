import json
import unittest

import bot


class RecordingWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


class FailingWebSocket(RecordingWebSocket):
    async def send(self, payload):
        self.sent.append(payload)
        raise RuntimeError("network down")


class WebSocketHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_heartbeat_once_sends_current_sequence(self):
        ws = RecordingWebSocket()

        result = await bot._send_heartbeat_once(ws, 123)

        self.assertTrue(result)
        self.assertEqual(ws.sent, [json.dumps({"op": 1, "d": 123})])
        self.assertFalse(ws.closed)

    async def test_send_heartbeat_once_closes_socket_after_send_failure(self):
        ws = FailingWebSocket()

        with self.assertLogs("OfficialBot", level="WARNING") as logs:
            result = await bot._send_heartbeat_once(ws, 456)

        self.assertFalse(result)
        self.assertTrue(ws.closed)
        self.assertIn("心跳发送失败", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
