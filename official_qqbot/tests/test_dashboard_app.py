import tempfile
import unittest
import os
import json
from unittest.mock import AsyncMock, patch

import yaml

from fastapi.testclient import TestClient

from control_api.app import create_app
from handlers.image_gen import GeneratedImage


class DashboardAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_local_state_dir = os.environ.get("LOCAL_STATE_DIR")
        os.environ["LOCAL_STATE_DIR"] = self.tmp.name
        self.config_path = os.path.join(self.tmp.name, "config.yaml")
        with open(self.config_path, "w", encoding="utf-8") as config_file:
            yaml.safe_dump(
                {
                    "bot": {"app_id": "app-1"},
                    "ai": {
                        "base_url": "https://api.example.test/v1",
                        "api_key": "sk-full-secret",
                        "model": "model-a",
                    },
                    "image_ai": {
                        "enabled": True,
                        "base_url": "https://image.example.test/v1",
                        "api_key": "ik-image-secret",
                        "model": "image-model-a",
                        "size": "1024x1024",
                        "cooldown_seconds": 60,
                    },
                },
                config_file,
                allow_unicode=True,
                sort_keys=False,
            )
        self.app = create_app(
            database_url=f"sqlite:///{self.tmp.name}/control.db",
            bot_token="bot-token",
            admin_token="admin-token",
            config_path=self.config_path,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        if self.old_local_state_dir is None:
            os.environ.pop("LOCAL_STATE_DIR", None)
        else:
            os.environ["LOCAL_STATE_DIR"] = self.old_local_state_dir
        self.tmp.cleanup()

    def test_dashboard_requires_login(self):
        resp = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/dashboard/login")

    def _login(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_ai_dashboard_requires_login(self):
        resp = self.client.get("/dashboard/ai", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/dashboard/login")

    def test_ai_dashboard_contains_chinese_form_and_masked_key_after_login(self):
        self._login()

        resp = self.client.get("/dashboard/ai")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("AI 对话", resp.text)
        self.assertIn("检测连接", resp.text)
        self.assertIn("保存并重启", resp.text)
        self.assertIn("sk-***cret", resp.text)
        self.assertNotIn("sk-full-secret", resp.text)

    def test_ai_test_route_does_not_save_config(self):
        self._login()
        manager = self.app.state.ai_config_manager
        form = {
            "base_url": "https://api.example.test/v2",
            "api_key": "new-secret",
            "model": "model-b",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(return_value=(True, "连接成功")),
        ), patch.object(manager, "save") as save:
            resp = self.client.post("/dashboard/ai/test", data=form)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("连接成功", resp.text)
        save.assert_not_called()

    def test_ai_save_route_checks_restarts_and_audits(self):
        self._login()
        manager = self.app.state.ai_config_manager
        form = {
            "base_url": "https://api.example.test/v2",
            "api_key": "new-secret",
            "model": "model-b",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(return_value=(True, "连接成功")),
        ), patch.object(manager, "save", return_value=b"old"), patch.object(
            manager,
            "restart_bot",
            return_value=(True, "Bot 已重启并使用新配置"),
        ):
            resp = self.client.post("/dashboard/ai/save", data=form)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bot 已重启并使用新配置", resp.text)
        self.assertTrue(
            any(
                item["action"] == "ai_config_update"
                for item in self.app.state.control_service.list_audit_logs()
            )
        )

    def test_ai_save_route_restores_when_restart_fails(self):
        self._login()
        manager = self.app.state.ai_config_manager
        form = {
            "base_url": "https://api.example.test/v2",
            "api_key": "new-secret",
            "model": "model-b",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(return_value=(True, "连接成功")),
        ), patch.object(manager, "save", return_value=b"old"), patch.object(
            manager,
            "restore",
        ) as restore, patch.object(
            manager,
            "restart_bot",
            return_value=(False, "Bot 重启失败"),
        ):
            resp = self.client.post("/dashboard/ai/save", data=form)

        self.assertEqual(resp.status_code, 503)
        self.assertIn("Bot 重启失败", resp.text)
        restore.assert_called_once_with(b"old")

    def test_ai_save_route_reports_config_write_failure(self):
        self._login()
        manager = self.app.state.ai_config_manager
        form = {
            "base_url": "https://api.example.test/v2",
            "api_key": "new-secret",
            "model": "model-b",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(return_value=(True, "连接成功")),
        ), patch.object(manager, "save", side_effect=OSError("read only")):
            resp = self.client.post("/dashboard/ai/save", data=form)

        self.assertEqual(resp.status_code, 500)
        self.assertIn("配置保存失败", resp.text)

    def test_image_ai_dashboard_requires_login(self):
        resp = self.client.get("/dashboard/image-ai", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/dashboard/login")

    def test_image_ai_dashboard_contains_chinese_form(self):
        self._login()

        resp = self.client.get("/dashboard/image-ai")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("AI 生图", resp.text)
        self.assertIn("API 地址", resp.text)
        self.assertIn("生图模型", resp.text)
        self.assertIn("图片尺寸", resp.text)
        self.assertIn("用户冷却", resp.text)
        self.assertIn("检测生图", resp.text)
        self.assertIn("保存并重启", resp.text)
        self.assertIn("ik-***cret", resp.text)
        self.assertNotIn("ik-image-secret", resp.text)

    def test_image_ai_test_route_previews_url_without_saving(self):
        self._login()
        manager = self.app.state.image_ai_config_manager
        form = {
            "enabled": "1",
            "base_url": "https://new-image.example.test/v1",
            "api_key": "new-image-key",
            "model": "new-image-model",
            "size": "1024x1024",
            "cooldown_seconds": "90",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(
                return_value=(
                    True,
                    "生图连接成功",
                    GeneratedImage(url="https://cdn.example.test/preview.png"),
                )
            ),
        ), patch.object(manager, "save") as save:
            resp = self.client.post("/dashboard/image-ai/test", data=form)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("生图连接成功", resp.text)
        self.assertIn("https://cdn.example.test/preview.png", resp.text)
        save.assert_not_called()

    def test_image_ai_test_route_previews_base64(self):
        self._login()
        manager = self.app.state.image_ai_config_manager
        form = {
            "enabled": "1",
            "base_url": "https://new-image.example.test/v1",
            "api_key": "new-image-key",
            "model": "new-image-model",
            "size": "1024x1024",
            "cooldown_seconds": "90",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(
                return_value=(True, "生图连接成功", GeneratedImage(b64_json="YWJj"))
            ),
        ):
            resp = self.client.post("/dashboard/image-ai/test", data=form)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("data:image/png;base64,YWJj", resp.text)

    def test_image_ai_save_checks_restarts_and_audits_without_key(self):
        self._login()
        manager = self.app.state.image_ai_config_manager
        form = {
            "enabled": "1",
            "base_url": "https://new-image.example.test/v1",
            "api_key": "new-image-key",
            "model": "new-image-model",
            "size": "1536x1024",
            "cooldown_seconds": "90",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(
                return_value=(
                    True,
                    "生图连接成功",
                    GeneratedImage(url="https://cdn.example.test/preview.png"),
                )
            ),
        ), patch.object(manager, "save", return_value=b"old"), patch.object(
            manager,
            "restart_bot",
            return_value=(True, "Bot 已重启并使用新配置"),
        ):
            resp = self.client.post("/dashboard/image-ai/save", data=form)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bot 已重启并使用新配置", resp.text)
        logs = self.app.state.control_service.list_audit_logs()
        image_logs = [item for item in logs if item["action"] == "image_ai_config_update"]
        self.assertEqual(len(image_logs), 1)
        self.assertIn("new-image-model", image_logs[0]["detail"])
        self.assertNotIn("new-image-key", image_logs[0]["detail"])

    def test_image_ai_save_restores_when_restart_fails(self):
        self._login()
        manager = self.app.state.image_ai_config_manager
        form = {
            "enabled": "1",
            "base_url": "https://new-image.example.test/v1",
            "api_key": "new-image-key",
            "model": "new-image-model",
            "size": "1024x1024",
            "cooldown_seconds": "90",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(
                return_value=(
                    True,
                    "生图连接成功",
                    GeneratedImage(url="https://cdn.example.test/preview.png"),
                )
            ),
        ), patch.object(manager, "save", return_value=b"old"), patch.object(
            manager, "restore"
        ) as restore, patch.object(
            manager, "restart_bot", return_value=(False, "Bot 重启失败")
        ):
            resp = self.client.post("/dashboard/image-ai/save", data=form)

        self.assertEqual(resp.status_code, 503)
        self.assertIn("Bot 重启失败", resp.text)
        restore.assert_called_once_with(b"old")

    def test_image_ai_save_reports_config_write_failure(self):
        self._login()
        manager = self.app.state.image_ai_config_manager
        form = {
            "enabled": "1",
            "base_url": "https://new-image.example.test/v1",
            "api_key": "new-image-key",
            "model": "new-image-model",
            "size": "1024x1024",
            "cooldown_seconds": "90",
        }

        with patch.object(
            manager,
            "check",
            new=AsyncMock(
                return_value=(
                    True,
                    "生图连接成功",
                    GeneratedImage(url="https://cdn.example.test/preview.png"),
                )
            ),
        ), patch.object(manager, "save", side_effect=OSError("read only")):
            resp = self.client.post("/dashboard/image-ai/save", data=form)

        self.assertEqual(resp.status_code, 500)
        self.assertIn("配置保存失败", resp.text)

    def test_dashboard_login_sets_session_cookie(self):
        resp = self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("dashboard_session=", resp.headers["set-cookie"])

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("控制台", resp.text)
        self.assertIn("广告管理", resp.text)
        self.assertIn("用户列表", resp.text)
        self.assertIn("权限管理", resp.text)
        self.assertIn("封禁名单", resp.text)
        self.assertNotIn("公告发布", resp.text)
        self.assertNotIn("更新包设置", resp.text)

        resp = self.client.get("/dashboard/ads")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("广告管理", resp.text)

    def test_dashboard_users_page_is_not_capped_at_500_users(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        service = self.app.state.control_service
        for index in range(501):
            service.upsert_seen_user(f"user-{index:03d}")

        resp = self.client.get("/dashboard/users")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("user-000", resp.text)
        self.assertIn("user-500", resp.text)

    def test_dashboard_overview_counts_all_users(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        service = self.app.state.control_service
        for index in range(501):
            service.upsert_seen_user(f"user-{index:03d}")

        resp = self.client.get("/dashboard")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("已记录 501 个 OpenID", resp.text)

    def test_dashboard_css_has_motion_and_interactive_polish(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        resp = self.client.get("/dashboard")

        self.assertIn("@keyframes consoleEnter", resp.text)
        self.assertIn("animation: consoleEnter", resp.text)
        self.assertIn(".panel:hover", resp.text)
        self.assertIn("button:hover", resp.text)
        self.assertIn("input:focus", resp.text)
        self.assertIn("transition: transform", resp.text)
        self.assertIn("@media (prefers-reduced-motion: reduce)", resp.text)

    def test_limits_dashboard_renders_touchable_usage_chart(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        service = self.app.state.control_service
        service.set_resource_limit("163", 3, "day", updated_by="admin")
        service.record_resource_usage("163", "user-a")

        resp = self.client.get("/dashboard/limits")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("实时获取统计", resp.text)
        self.assertIn("usage-chart", resp.text)
        self.assertIn("data-tooltip", resp.text)
        self.assertIn("秒", resp.text)
        self.assertIn("分钟", resp.text)
        self.assertIn("小时", resp.text)
        self.assertIn("天", resp.text)
        self.assertIn("月", resp.text)
        self.assertIn("年", resp.text)
        self.assertIn("touchstart", resp.text)

    def test_limits_dashboard_supports_switchable_chart_types(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        service = self.app.state.control_service
        service.set_resource_limit("163", 3, "day", updated_by="admin")
        service.record_resource_usage("163", "user-a")

        resp = self.client.get("/dashboard/limits")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("data-chart-type='line'", resp.text)
        self.assertIn("data-chart-type='pie'", resp.text)
        self.assertIn("data-chart-type='radar'", resp.text)
        self.assertIn("data-chart-type='bar'", resp.text)
        self.assertIn("chart-tab is-active", resp.text)
        self.assertIn("折线图", resp.text)
        self.assertIn("饼状图", resp.text)
        self.assertIn("雷达图", resp.text)
        self.assertIn("柱状图", resp.text)
        self.assertIn("switchChart", resp.text)

    def test_dashboard_can_ban_user(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = self.client.post(
            "/dashboard/users/user-a/ban",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

        service = self.app.state.control_service
        self.assertTrue(service.is_banned("user-a"))

    def test_dashboard_can_create_ad(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = self.client.post(
            "/dashboard/ads",
            content="content=测试广告内容&enabled=1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

        resp = self.client.get("/dashboard/ads")
        self.assertIn("测试广告内容", resp.text)

    def test_dashboard_can_create_ad_with_expiry(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = self.client.post(
            "/dashboard/ads",
            content=(
                "content=限时广告&enabled=1&active_until=2026-05-29T12%3A30%3A45"
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

        resp = self.client.get("/dashboard/ads")

        self.assertIn("限时广告", resp.text)
        self.assertIn("2026-05-29 12:30:45", resp.text)
        self.assertIn("expiry-form", resp.text)
        self.assertIn("expiry-row", resp.text)
        self.assertIn("当前：2026-05-29 12:30:45", resp.text)
        self.assertIn("月费到期", resp.text)

    def test_dashboard_read_expires_ads_without_bot_online(self):
        ads_path = os.path.join(self.tmp.name, "ads.json")
        with open(ads_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": 1,
                        "content": "过期广告",
                        "enabled": True,
                        "active_until": 1,
                    }
                ],
                f,
                ensure_ascii=False,
            )
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        self.client.get("/dashboard/ads")

        with open(ads_path, "r", encoding="utf-8") as f:
            ads = json.load(f)
        self.assertFalse(ads[0]["enabled"])

    def test_dashboard_can_ban_openid_directly(self):
        self.client.post(
            "/dashboard/login",
            content="token=admin-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = self.client.post(
            "/dashboard/bans",
            content="user_key=direct-user&reason=manual",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(self.app.state.control_service.is_banned("direct-user"))


if __name__ == "__main__":
    unittest.main()
