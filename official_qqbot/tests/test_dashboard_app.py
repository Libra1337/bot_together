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

    def test_dashboard_has_accessible_navigation_and_responsive_shell(self):
        self._login()
        text = self.client.get("/dashboard").text
        self.assertIn('aria-current="page"', text)
        self.assertIn('aria-expanded="false"', text)
        self.assertIn('prefers-reduced-motion', text)
        self.assertIn(':focus-visible', text)
        self.assertEqual(text.count('<h1'), 1)

    def test_limits_dashboard_shows_totals_and_personal_quotas_separately(self):
        self._login()
        service = self.app.state.control_service
        service.set_resource_limit("163", 3, "day", updated_by="admin")
        service.record_resource_usage("163", "user-a")
        text = self.client.get("/dashboard/limits").text
        self.assertIn("资源用量总览", text)
        self.assertIn("用户用量明细", text)
        self.assertIn("近 24 小时", text)
        self.assertIn("不能相加", text)
        self.assertIn("1 / 3", text)
        self.assertIn("可继续获取", text)
        self.assertIn("最早一条记录释放", text)
        self.assertNotIn('data-chart-type', text)

    def test_limits_filters_are_server_rendered_and_escape_user_input(self):
        self._login()
        service = self.app.state.control_service
        service.set_resource_limit("163", 1, "day")
        service.set_resource_limit("4399", 1, "day")
        service.record_resource_usage("163", "user-a")
        service.record_resource_usage("4399", "user-b")
        response = self.client.get("/dashboard/limits?resource=163&q=user-a")
        self.assertIn("user-a", response.text)
        self.assertNotIn("user-b", response.text)
        self.assertIn("已达限额", response.text)
        response = self.client.get('/dashboard/limits', params={"q": '<script>alert(1)</script>', "page": "bad"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)</script>', response.text)
        self.assertIn("暂无有效用量", response.text)

    def test_limits_form_validates_and_persists(self):
        self._login()
        invalid = self.client.post('/dashboard/resource-limits', data={"resource": "163", "limit_count": "abc", "window_unit": "day"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('role="alert"', invalid.text)
        valid = self.client.post('/dashboard/resource-limits', data={"resource": "163", "limit_count": "5", "window_unit": "hour"})
        self.assertEqual(valid.status_code, 200)
        self.assertIn("限制规则已保存", valid.text)
        self.assertEqual(self.app.state.control_service.get_resource_limit('163')['limit_count'], 5)

    def test_rule_view_prefills_current_values_and_retains_invalid_input(self):
        self._login()
        self.app.state.control_service.set_resource_limit("4399", 27, "hour")
        usage = self.client.get('/dashboard/limits').text
        self.assertNotIn('id="count-4399"', usage)
        rules = self.client.get('/dashboard/limits?view=rules').text
        self.assertIn('value="27"', rules)
        self.assertIn('<option value="hour" selected>', rules)
        self.assertNotIn('id="usage-query"', rules)
        invalid = self.client.post('/dashboard/resource-limits', data={"resource": "4399", "limit_count": "0", "window_unit": "hour"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('id="rule-4399" open', invalid.text)
        self.assertIn('value="0"', invalid.text)
        self.assertEqual(self.app.state.control_service.get_resource_limit('4399')['limit_count'], 27)

    def test_log_view_selects_one_record_type_and_handles_unknown_view(self):
        self._login()
        service = self.app.state.control_service
        with patch.object(service, 'list_command_logs', return_value=[]) as commands, patch.object(service, 'list_audit_logs', return_value=[]) as audit:
            response = self.client.get('/dashboard/logs?view=audit')
            self.assertEqual(response.status_code, 200)
            audit.assert_called_once_with(limit=50)
            commands.assert_not_called()
            self.client.get('/dashboard/logs?view=unknown')
            commands.assert_called_once_with(limit=50)

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
