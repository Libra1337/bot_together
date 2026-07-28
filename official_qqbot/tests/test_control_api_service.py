import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from control_api.db import create_app_engine, init_db
from control_api.service import ControlService


class ControlApiServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_app_engine(f"sqlite:///{self.tmp.name}/control.db")
        init_db(self.engine)
        self.service = ControlService(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_set_rule_check_usage_and_reset(self):
        self.service.set_resource_limit("163", 1, "day", updated_by="admin")
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))

        self.service.record_resource_usage(
            "163", "user-a", source_group_openid="group-1", message_id="msg-1"
        )
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertTrue(blocked)
        self.assertEqual((count, limit, window), (1, 1, 86400))

        self.service.reset_resource_usage()
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))

    def test_resource_limit_status_reports_reset_after(self):
        base = datetime(2026, 5, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.service.set_resource_limit("163", 2, "hour", updated_by="admin")
        self.service.record_resource_usage("163", "user-a", used_at=base)

        status = self.service.get_resource_limit_status(
            "163", "user-a", now=base + timedelta(minutes=20)
        )

        self.assertFalse(status["blocked"])
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["limit"], 2)
        self.assertEqual(status["window"], 3600)
        self.assertEqual(status["reset_after"], 2400)

    def test_resource_usage_stats_cover_standard_ranges(self):
        base = datetime(2026, 5, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.service.set_resource_limit("163", 10, "day", updated_by="admin")
        self.service.record_resource_usage("163", "user-a", used_at=base)
        self.service.record_resource_usage("163", "user-b", used_at=base - timedelta(seconds=30))
        self.service.record_resource_usage("163", "user-c", used_at=base - timedelta(hours=2))

        stats = self.service.list_resource_usage_stats(now=base + timedelta(seconds=1))

        row = next(item for item in stats if item["resource"] == "163")
        self.assertEqual(row["counts"]["second"], 1)
        self.assertEqual(row["counts"]["minute"], 2)
        self.assertEqual(row["counts"]["hour"], 2)
        self.assertEqual(row["counts"]["day"], 3)
        self.assertEqual(row["limit_count"], 10)


if __name__ == "__main__":
    unittest.main()
