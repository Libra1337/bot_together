import json
import tempfile
import time
import unittest
from pathlib import Path

from control_api.db import create_app_engine, init_db
from control_api.migrate_local_state import migrate_local_state
from control_api.service import ControlService


class ControlApiMigrationTests(unittest.TestCase):
    def test_migration_imports_local_json_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "admins.json").write_text('["admin-a"]', encoding="utf-8")
            (root / "banned.json").write_text('["banned-a"]', encoding="utf-8")
            (root / "email_binds.json").write_text(
                '{"user-a":"a@example.com"}', encoding="utf-8"
            )
            now = int(time.time())
            (root / "cooldowns.json").write_text(
                json.dumps(
                    {
                        "restrict_rules": {
                            "163": {
                                "limit": 1,
                                "unit": "day",
                                "window": 86400,
                            }
                        },
                        "restrict_log": {"163": {"user-a": [now]}},
                    }
                ),
                encoding="utf-8",
            )

            engine = create_app_engine(f"sqlite:///{root}/control.db")
            init_db(engine)
            migrate_local_state(root, engine)
            migrate_local_state(root, engine)
            service = ControlService(engine)

            self.assertEqual(service.get_email_binding("user-a"), "a@example.com")
            self.assertTrue(service.is_banned("banned-a"))
            self.assertIn("admin", service.get_user_state("admin-a")["roles"])
            users = {item["user_key"] for item in service.list_users(limit=20)}
            self.assertTrue({"admin-a", "banned-a", "user-a"}.issubset(users))
            self.assertEqual(service.get_resource_limit("163")["limit_count"], 1)
            blocked, count, limit, window = service.check_resource_limit(
                "163", "user-a"
            )
            self.assertEqual((blocked, count, limit, window), (True, 1, 1, 86400))
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
