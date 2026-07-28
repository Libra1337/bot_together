import os
import subprocess
import sys
import textwrap
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoneBotDeployTests(unittest.TestCase):
    def test_requirements_include_nonebot_adapter_qq(self):
        with open(os.path.join(ROOT, "requirements.txt"), "r", encoding="utf-8") as f:
            requirements = f.read()

        self.assertIn("nonebot2[httpx,websockets]", requirements)
        self.assertIn("nonebot-adapter-qq", requirements)

    def test_nonebot_bridge_service_runs_nonebot_entrypoint(self):
        service_path = os.path.join(ROOT, "deploy", "ubuntu", "nonebot-bridge.service")
        with open(service_path, "r", encoding="utf-8") as f:
            service = f.read()

        self.assertIn("ExecStart=/opt/official_qqbot/.venv/bin/python nonebot_bridge.py", service)
        self.assertIn("EnvironmentFile=/etc/official-qqbot/koishi-bridge.env", service)

    def test_install_script_installs_nonebot_bridge_service(self):
        with open(os.path.join(ROOT, "deploy", "ubuntu", "install.sh"), "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("nonebot-bridge.service", script)

    def test_nonebot_bridge_main_registers_event_handler(self):
        script = textwrap.dedent(
            """
            import nonebot
            import nonebot_bridge
            from nonebot.adapters.qq import Adapter as QQAdapter
            from nonebot.matcher import matchers

            def configure():
                nonebot.init(driver="~httpx+~websockets", qq_bots=[])
                nonebot.get_driver().register_adapter(QQAdapter)
                nonebot_bridge._register_group_message_event()
                return "http://127.0.0.1:9/koishi/message", "", set()

            called = {"run": False}

            def fake_run(*args, **kwargs):
                called["run"] = True

            nonebot_bridge._configure_nonebot = configure
            nonebot.run = fake_run

            nonebot_bridge.main()
            assert called["run"]
            assert any(matcher.type == "message" for matcher in matchers[1])
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("Unknown ForwardRef", result.stderr + result.stdout)
        self.assertNotIn("NameError", result.stderr + result.stdout)

    def test_custom_group_message_event_parses_author(self):
        script = textwrap.dedent(
            """
            from nonebot.compat import type_validate_python
            from nonebot.adapters.qq.adapter import Adapter
            from nonebot.adapters.qq.models.payload import Dispatch
            import nonebot_bridge
            from adapters.nonebot_bridge import event_to_bridge_payload

            nonebot_bridge._register_group_message_event()
            payload = type_validate_python(
                Dispatch,
                {
                    "op": 0,
                    "id": "payload-id",
                    "s": 1,
                    "t": "GROUP_MESSAGE_CREATE",
                    "d": {
                        "id": "msg-id",
                        "content": "menu",
                        "timestamp": "2026-05-18T00:00:00+08:00",
                        "group_openid": "group-openid",
                        "author": {
                            "id": "author-id",
                            "member_openid": "member-openid",
                        },
                    },
                },
            )

            event = Adapter.payload_to_event(payload)
            bridge_payload = event_to_bridge_payload(event, {"group-openid"})

            assert event.get_event_name() == "GROUP_MESSAGE_CREATE"
            assert event.get_session_id() == "group_group-openid_member-openid"
            assert bridge_payload["user_openid"] == "member-openid"
            assert bridge_payload["content"] == "menu"
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
