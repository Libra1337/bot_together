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

    def test_usage_summary_includes_unconfigured_resources_and_excludes_future_records(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.service.record_resource_usage("nfa", "user", used_at=now)
        self.service.record_resource_usage("nfa", "user", used_at=now + timedelta(seconds=1))
        stats = self.service.list_resource_usage_stats(now=now)
        self.assertEqual(len(stats), 4)
        self.assertEqual(
            {row["resource"] for row in stats}, {"163", "4399", "sauth", "nfa"}
        )
        nfa = next(row for row in stats if row["resource"] == "nfa")
        self.assertEqual(nfa["counts"]["day"], 1)
        self.assertEqual(nfa["limit_count"], 0)

    def test_user_usage_counts_windows_and_keeps_nfa_quota(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.service.set_resource_limit("nfa", 2, "hour")
        for second in (30, 120, 3700):
            self.service.record_resource_usage("sauth", "user-a", used_at=now - timedelta(seconds=second))
        self.service.record_resource_usage("sauth", "user-b", used_at=now)
        for minute in (10, 20, 61):
            self.service.record_resource_usage("nfa", "user-a", used_at=now - timedelta(minutes=minute))
        result = self.service.list_resource_user_usage(now=now)
        a_sauth = next(row for row in result["items"] if row["user_key"] == "user-a" and row["resource"] == "sauth")
        self.assertTrue(a_sauth["is_points"])
        self.assertEqual((a_sauth["counts"]["minute"], a_sauth["counts"]["hour"], a_sauth["counts"]["day"]), (1, 2, 3))
        self.assertFalse(a_sauth["blocked"])
        a_nfa = next(row for row in result["items"] if row["user_key"] == "user-a" and row["resource"] == "nfa")
        self.assertFalse(a_nfa["is_points"])
        self.assertEqual((a_nfa["quota_used"], a_nfa["remaining"], a_nfa["blocked"], a_nfa["reset_after"]), (2, 0, True, 2400))
        self.assertEqual(result["total"], 3)

    def test_user_usage_filters_paginates_and_escapes_like_wildcards(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        for user in ("user-a", "user-b", "user-%"):
            self.service.record_resource_usage("163", user, used_at=now)
        result = self.service.list_resource_user_usage(now=now, page=2, page_size=2)
        self.assertEqual((result["total"], result["page"], len(result["items"])), (3, 2, 1))
        filtered = self.service.list_resource_user_usage(now=now, query="%")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["user_key"], "user-%")


if __name__ == "__main__":
    unittest.main()
