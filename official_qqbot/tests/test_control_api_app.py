import tempfile
import unittest

from fastapi.testclient import TestClient

from control_api.app import create_app


class ControlApiAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(
            database_url=f"sqlite:///{self.tmp.name}/control.db",
            bot_token="bot-token",
            admin_token="admin-token",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_internal_limit_route_requires_bot_token(self):
        resp = self.client.get("/internal/resource-limits/163/check?user_key=user-a")
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get(
            "/internal/resource-limits/163/check?user_key=user-a",
            headers={"X-Bot-Token": "bot-token"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_set_and_check_limit_through_api(self):
        self.client.post(
            "/internal/resource-limits",
            headers={"X-Bot-Token": "bot-token"},
            json={"resource": "163", "limit_count": 1, "window_unit": "day"},
        )
        resp = self.client.get(
            "/internal/resource-limits/163/check?user_key=user-a",
            headers={"X-Bot-Token": "bot-token"},
        )
        self.assertEqual(resp.json()["blocked"], False)
        self.assertIn("reset_after", resp.json())

    def test_internal_usage_stats_route_returns_standard_ranges(self):
        self.client.post(
            "/internal/resource-limits",
            headers={"X-Bot-Token": "bot-token"},
            json={"resource": "163", "limit_count": 3, "window_unit": "day"},
        )
        self.client.post(
            "/internal/resource-usage",
            headers={"X-Bot-Token": "bot-token"},
            json={"resource": "163", "user_key": "user-a"},
        )

        resp = self.client.get(
            "/internal/resource-usage/stats",
            headers={"X-Bot-Token": "bot-token"},
        )

        self.assertEqual(resp.status_code, 200)
        item = next(row for row in resp.json()["items"] if row["resource"] == "163")
        self.assertEqual(item["counts"]["day"], 1)
        self.assertIn("second", item["counts"])
        self.assertIn("year", item["counts"])


if __name__ == "__main__":
    unittest.main()
