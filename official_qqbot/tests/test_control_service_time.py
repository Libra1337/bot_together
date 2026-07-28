import tempfile
import unittest
from datetime import datetime, timezone

from control_api.db import create_app_engine, init_db, session_scope
from control_api.models import CommandLog
from control_api.service import ControlService, format_beijing_datetime


class ControlServiceTimeTests(unittest.TestCase):
    def test_formats_utc_as_beijing_display_time(self):
        value = datetime(2026, 5, 29, 3, 38, 29, 565555, tzinfo=timezone.utc)

        self.assertEqual(format_beijing_datetime(value), "2026-05-29-11:38:29")

    def test_command_logs_return_beijing_display_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = create_app_engine(f"sqlite:///{tmp}/control.db")
            init_db(engine)
            service = ControlService(engine)
            with session_scope(engine) as session:
                session.add(
                    CommandLog(
                        user_key="user-a",
                        command="/help",
                        content="/help",
                        created_at=datetime(
                            2026, 5, 29, 3, 38, 29, 565555, tzinfo=timezone.utc
                        ),
                    )
                )

            logs = service.list_command_logs()

        self.assertEqual(logs[0]["created_at"], "2026-05-29-11:38:29")


if __name__ == "__main__":
    unittest.main()
