import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from control_api.db import create_app_engine, init_db
from control_api.service import ControlService


class ControlApiServiceTests(unittest.TestCase):
    def test_usage_trend_has_disjoint_buckets_and_excludes_future_records(self):
        now = datetime(2026, 10, 4, 17, 30, tzinfo=timezone.utc)
        for resource, stamp in [
            ("163", now.replace(minute=0)),
            ("163", now.replace(minute=0) - timedelta(microseconds=1)),
            ("4399", now),
            ("nfa", now + timedelta(seconds=1)),
            ("nfa", now - timedelta(days=2)),
        ]:
            self.service.record_resource_usage(resource, "trend-user", used_at=stamp)
        trend = self.service.resource_usage_trend("hour", now=now)
        self.assertEqual(len(trend['labels']), 24)
        self.assertEqual(trend['labels'][-1], '10-05 01:00')
        self.assertEqual(trend['series']['163'][-2:], [1, 1])
        self.assertEqual(trend['series']['4399'][-1], 1)
        self.assertEqual(sum(trend['series']['nfa']), 0)
        self.assertEqual(trend['total'], 3)
        self.assertEqual(self.service.resource_usage_trend('invalid', now=now)['interval'], 'hour')

    def test_daily_usage_trend_uses_beijing_midnight_and_zero_fills(self):
        now = datetime(2026, 10, 4, 17, 30, tzinfo=timezone.utc)
        midnight = datetime(2026, 10, 4, 16, tzinfo=timezone.utc)
        self.service.record_resource_usage('163', 'before', used_at=midnight-timedelta(seconds=1))
        self.service.record_resource_usage('163', 'after', used_at=midnight)
        trend = self.service.resource_usage_trend('day', now=now)
        self.assertEqual(trend['labels'][-1], '10-05 00:00')
        self.assertEqual(trend['series']['163'], [0, 0, 0, 0, 0, 1, 1])
        minute = self.service.resource_usage_trend('minute', now=now)
        self.assertEqual(len(minute['labels']), 60)
        self.assertEqual(minute['total'], 0)

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
        self.assertEqual(len(stats), 3)
        nfa = next(row for row in stats if row["resource"] == "nfa")
        self.assertEqual(nfa["counts"]["day"], 1)
        self.assertEqual(nfa["limit_count"], 0)

    def test_user_usage_uses_each_rules_window_and_own_quota(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.service.set_resource_limit("163", 2, "hour")
        self.service.set_resource_limit("4399", 1, "day")
        for minute in (10, 20, 61):
            self.service.record_resource_usage("163", "user-a", used_at=now - timedelta(minutes=minute))
        self.service.record_resource_usage("163", "user-b", used_at=now)
        self.service.record_resource_usage("4399", "user-a", used_at=now - timedelta(hours=2))
        result = self.service.list_resource_user_usage(now=now)
        a = next(row for row in result["items"] if row["user_key"] == "user-a" and row["resource"] == "163")
        self.assertEqual((a["used"], a["remaining"], a["blocked"], a["reset_after"]), (2, 0, True, 2400))
        b = next(row for row in result["items"] if row["user_key"] == "user-b")
        self.assertEqual((b["used"], b["remaining"], b["blocked"]), (1, 1, False))
        self.assertEqual(result["total"], 3)

    def test_user_usage_filters_paginates_and_escapes_like_wildcards(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.service.set_resource_limit("163", 2, "hour")
        for user in ("user-a", "user-b", "user-%"):
            self.service.record_resource_usage("163", user, used_at=now)
        result = self.service.list_resource_user_usage(now=now, page=2, page_size=2)
        self.assertEqual((result["total"], result["page"], len(result["items"])), (3, 2, 1))
        filtered = self.service.list_resource_user_usage(now=now, query="%")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["user_key"], "user-%")


if __name__ == "__main__":
    unittest.main()
