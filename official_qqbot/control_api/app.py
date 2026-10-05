import hashlib
import hmac
import html
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .ai_config import AIConfigManager, AISettings
from .auth import require_admin_token, require_bot_token
from .db import create_app_engine, init_db
from .dashboard_ui import render_layout, render_login
from . import dashboard_usage as usage_ui
from .image_ai_config import IMAGE_SIZES, ImageAIConfigManager, ImageAISettings
from .schemas import (
    BanRequest,
    CommandLogRequest,
    EmailBindingRequest,
    OutboundLogRequest,
    ResourceLimitRequest,
    ResourceUsageRequest,
    RoleRequest,
    SeenUserRequest,
)
from .service import ControlService


BEIJING_TZ = timezone(timedelta(hours=8))


def create_app(
    database_url: str,
    bot_token: str,
    admin_token: str,
    config_path: str | Path | None = None,
) -> FastAPI:
    engine = create_app_engine(database_url)
    init_db(engine)
    service = ControlService(engine)
    app = FastAPI(title="Official QQBot Control API")
    app.state.engine = engine
    app.state.control_service = service
    resolved_config_path = config_path or os.getenv("BOT_CONFIG_PATH", "")
    if not resolved_config_path:
        resolved_config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    app.state.ai_config_manager = AIConfigManager(resolved_config_path)
    app.state.image_ai_config_manager = ImageAIConfigManager(resolved_config_path)

    bot_guard = Depends(require_bot_token(bot_token))
    admin_guard = Depends(require_admin_token(admin_token))
    dashboard_secret = os.getenv("DASHBOARD_SESSION_SECRET", "") or admin_token

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/qq")
    async def qq_webhook_proxy(request: Request):
        body = await request.body()
        forward_url = os.getenv(
            "QQ_WEBHOOK_FORWARD_URL",
            "http://127.0.0.1:8765/qq",
        )
        status_code, content, content_type = await _forward_qq_webhook(
            body,
            dict(request.headers),
            _with_query_string(forward_url, request.url.query),
        )
        return Response(
            content=content,
            status_code=status_code,
            media_type=content_type,
        )

    @app.post("/internal/events/seen", dependencies=[bot_guard])
    def seen_user(req: SeenUserRequest):
        return service.upsert_seen_user(
            req.user_key,
            display_name=req.display_name,
            group_openid=req.group_openid,
        )

    @app.get("/internal/users/{user_key}/state", dependencies=[bot_guard])
    def get_user_state(user_key: str):
        return service.get_user_state(user_key)

    @app.post("/internal/email-bindings", dependencies=[bot_guard])
    def set_email_binding(req: EmailBindingRequest):
        service.set_email_binding(req.user_key, req.email)
        return {"ok": True}

    @app.delete("/internal/email-bindings/{user_key}", dependencies=[bot_guard])
    def delete_email_binding(user_key: str):
        service.delete_email_binding(user_key)
        return {"ok": True}

    @app.get("/internal/resource-limits/{resource}/check", dependencies=[bot_guard])
    def check_resource_limit(resource: str, user_key: str):
        return service.get_resource_limit_status(resource, user_key)

    @app.get("/internal/resource-usage/stats", dependencies=[bot_guard])
    def resource_usage_stats():
        return {"items": service.list_resource_usage_stats()}

    @app.post("/internal/resource-usage", dependencies=[bot_guard])
    def record_resource_usage(req: ResourceUsageRequest):
        service.record_resource_usage(
            req.resource,
            req.user_key,
            source_group_openid=req.source_group_openid,
            message_id=req.message_id,
        )
        return {"ok": True}

    @app.post("/internal/resource-limits", dependencies=[bot_guard])
    def set_internal_resource_limit(req: ResourceLimitRequest):
        return service.set_resource_limit(
            req.resource,
            req.limit_count,
            req.window_unit,
            updated_by=req.updated_by,
        )

    @app.post("/internal/resource-limits/reset-usage", dependencies=[bot_guard])
    def reset_resource_usage():
        service.reset_resource_usage()
        return {"ok": True}

    @app.post("/internal/logs/command", dependencies=[bot_guard])
    def log_command(req: CommandLogRequest):
        service.log_command(
            user_key=req.user_key,
            group_openid=req.group_openid,
            command=req.command,
            content=req.content,
            message_id=req.message_id,
        )
        return {"ok": True}

    @app.post("/internal/logs/outbound", dependencies=[bot_guard])
    def log_outbound(req: OutboundLogRequest):
        service.log_outbound(
            user_key=req.user_key,
            group_openid=req.group_openid,
            channel=req.channel,
            status=req.status,
            content=req.content,
            message_id=req.message_id,
        )
        return {"ok": True}

    @app.post("/internal/users/{user_key}/ban", dependencies=[bot_guard])
    def internal_ban_user(user_key: str, req: BanRequest):
        service.set_banned(user_key, True, reason=req.reason)
        return {"ok": True}

    @app.post("/internal/users/{user_key}/unban", dependencies=[bot_guard])
    def internal_unban_user(user_key: str):
        service.set_banned(user_key, False)
        return {"ok": True}

    @app.post("/internal/roles", dependencies=[bot_guard])
    def internal_add_role(req: RoleRequest):
        service.add_role(
            req.user_key,
            req.role,
            password=req.password,
            added_by=req.added_by,
        )
        return {"ok": True}

    @app.get("/internal/roles/{role}/{user_key}", dependencies=[bot_guard])
    def internal_get_role(role: str, user_key: str):
        return service.get_role(user_key, role) or {}

    @app.delete("/internal/roles/{role}/{user_key}", dependencies=[bot_guard])
    def internal_delete_role(role: str, user_key: str):
        service.revoke_role(user_key, role)
        return {"ok": True}

    @app.get("/admin/users", dependencies=[admin_guard])
    def list_users(limit: int = 100):
        return {"items": service.list_users(limit=limit)}

    @app.patch("/admin/users/{user_key}", dependencies=[admin_guard])
    def patch_user(user_key: str, payload: dict):
        if "is_banned" in payload:
            service.set_banned(
                user_key,
                bool(payload["is_banned"]),
                reason=str(payload.get("reason", "")),
                updated_by=str(payload.get("updated_by", "")),
            )
        return service.get_user_state(user_key)

    @app.get("/admin/resource-limits", dependencies=[admin_guard])
    def list_resource_limits():
        return {"items": service.list_resource_limits()}

    @app.patch("/admin/resource-limits/{resource}", dependencies=[admin_guard])
    def patch_resource_limit(resource: str, payload: dict):
        return service.set_resource_limit(
            resource,
            int(payload["limit_count"]),
            str(payload["window_unit"]),
            updated_by=str(payload.get("updated_by", "")),
        )

    @app.get("/admin/logs/commands", dependencies=[admin_guard])
    def list_command_logs(limit: int = 100):
        return {"items": service.list_command_logs(limit=limit)}

    @app.get("/admin/logs/audit", dependencies=[admin_guard])
    def list_audit_logs(limit: int = 100):
        return {"items": service.list_audit_logs(limit=limit)}

    @app.get("/admin/logs/outbound", dependencies=[admin_guard])
    def list_outbound_logs(limit: int = 100):
        return {"items": service.list_outbound_logs(limit=limit)}

    @app.get("/dashboard/login", response_class=HTMLResponse)
    def dashboard_login():
        return HTMLResponse(_login_html())

    @app.post("/dashboard/login")
    async def dashboard_login_post(request: Request):
        form = await _read_urlencoded_form(request)
        if form.get("token", "") != admin_token:
            return HTMLResponse(_login_html(error="管理密钥不正确"), status_code=401)
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie(
            "dashboard_session",
            _sign_dashboard_session(dashboard_secret),
            httponly=True,
            samesite="lax",
            max_age=12 * 3600,
        )
        return resp

    @app.post("/dashboard/logout")
    def dashboard_logout():
        resp = RedirectResponse("/dashboard/login", status_code=303)
        resp.delete_cookie("dashboard_session")
        return resp

    @app.head("/dashboard")
    def dashboard_head(request: Request):
        if not _dashboard_authenticated(request, dashboard_secret):
            return Response(status_code=303, headers={"location": "/dashboard/login"})
        return Response(status_code=200)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_overview_page(service))

    @app.get("/dashboard/ads", response_class=HTMLResponse)
    def dashboard_ads(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_ads_page(service))

    @app.get("/dashboard/users", response_class=HTMLResponse)
    def dashboard_users(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_users_page(service))

    @app.get("/dashboard/permissions", response_class=HTMLResponse)
    def dashboard_permissions(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_permissions_page(service))

    @app.get("/dashboard/bans", response_class=HTMLResponse)
    def dashboard_bans(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_bans_page(service))

    @app.get("/dashboard/limits", response_class=HTMLResponse)
    def dashboard_limits(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_limits_page(service, request.query_params))

    @app.get("/dashboard/logs", response_class=HTMLResponse)
    def dashboard_logs(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_logs_page(service, request.query_params))

    @app.get("/dashboard/settings", response_class=HTMLResponse)
    def dashboard_settings(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_settings_page(service))

    @app.get("/dashboard/ai", response_class=HTMLResponse)
    def dashboard_ai(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_ai_page(app.state.ai_config_manager))

    @app.post("/dashboard/ai/test", response_class=HTMLResponse)
    async def dashboard_ai_test(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        manager = app.state.ai_config_manager
        form = await _read_urlencoded_form(request)
        settings = _ai_settings_from_form(manager, form)
        ok, message = await manager.check(settings)
        return HTMLResponse(
            _ai_page(
                manager,
                notice=message if ok else "",
                error="" if ok else message,
                base_url=settings.base_url,
                model=settings.model,
            ),
            status_code=200 if ok else 400,
        )

    @app.post("/dashboard/ai/save", response_class=HTMLResponse)
    async def dashboard_ai_save(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        manager = app.state.ai_config_manager
        form = await _read_urlencoded_form(request)
        settings = _ai_settings_from_form(manager, form)
        ok, message = await manager.check(settings)
        if not ok:
            return HTMLResponse(
                _ai_page(
                    manager,
                    error=message,
                    base_url=settings.base_url,
                    model=settings.model,
                ),
                status_code=400,
            )

        try:
            snapshot = manager.save(settings)
        except (OSError, ValueError):
            return HTMLResponse(
                _ai_page(
                    manager,
                    error="配置保存失败，请检查配置文件权限",
                    base_url=settings.base_url,
                    model=settings.model,
                ),
                status_code=500,
            )
        restarted, restart_message = manager.restart_bot()
        if not restarted:
            manager.restore(snapshot)
            manager.restart_bot()
            return HTMLResponse(
                _ai_page(
                    manager,
                    error=restart_message,
                    base_url=manager.load().base_url,
                    model=manager.load().model,
                ),
                status_code=503,
            )

        service.log_audit(
            "ai_config_update",
            actor_user_key="dashboard",
            detail=f"base_url={settings.base_url}; model={settings.model}",
        )
        return HTMLResponse(
            _ai_page(
                manager,
                notice=restart_message,
                base_url=settings.base_url,
                model=settings.model,
            )
        )

    @app.get("/dashboard/image-ai", response_class=HTMLResponse)
    def dashboard_image_ai(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_image_ai_page(app.state.image_ai_config_manager))

    @app.post("/dashboard/image-ai/test", response_class=HTMLResponse)
    async def dashboard_image_ai_test(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        manager = app.state.image_ai_config_manager
        form = await _read_urlencoded_form(request)
        settings = _image_ai_settings_from_form(manager, form)
        ok, message, preview = await manager.check(settings)
        return HTMLResponse(
            _image_ai_page(
                manager,
                notice=message if ok else "",
                error="" if ok else message,
                settings=settings,
                preview=preview,
            ),
            status_code=200 if ok else 400,
        )

    @app.post("/dashboard/image-ai/save", response_class=HTMLResponse)
    async def dashboard_image_ai_save(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        manager = app.state.image_ai_config_manager
        form = await _read_urlencoded_form(request)
        settings = _image_ai_settings_from_form(manager, form)
        preview = None
        if settings.enabled:
            ok, message, preview = await manager.check(settings)
            if not ok:
                return HTMLResponse(
                    _image_ai_page(
                        manager,
                        error=message,
                        settings=settings,
                    ),
                    status_code=400,
                )
        else:
            validation_error = manager.validate(settings)
            if validation_error:
                return HTMLResponse(
                    _image_ai_page(
                        manager,
                        error=validation_error,
                        settings=settings,
                    ),
                    status_code=400,
                )

        try:
            snapshot = manager.save(settings)
        except (OSError, ValueError):
            return HTMLResponse(
                _image_ai_page(
                    manager,
                    error="配置保存失败，请检查配置文件权限",
                    settings=settings,
                ),
                status_code=500,
            )

        restarted, restart_message = manager.restart_bot()
        if not restarted:
            manager.restore(snapshot)
            manager.restart_bot()
            return HTMLResponse(
                _image_ai_page(
                    manager,
                    error=restart_message,
                    settings=manager.load(),
                ),
                status_code=503,
            )

        service.log_audit(
            "image_ai_config_update",
            actor_user_key="dashboard",
            detail=(
                f"enabled={settings.enabled}; base_url={settings.base_url}; "
                f"model={settings.model}; size={settings.size}; "
                f"cooldown_seconds={settings.cooldown_seconds}"
            ),
        )
        return HTMLResponse(
            _image_ai_page(
                manager,
                notice=restart_message,
                settings=settings,
                preview=preview,
            )
        )

    @app.post("/dashboard/ads")
    async def dashboard_create_ad(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        active_until = _parse_active_until(form.get("active_until", ""))
        _create_ad(
            form.get("content", ""),
            form.get("enabled", "") == "1",
            active_until=active_until,
        )
        service.log_audit(
            "ad_create",
            actor_user_key="dashboard",
            detail=form.get("content", "")[:160],
        )
        return RedirectResponse("/dashboard/ads", status_code=303)

    @app.post("/dashboard/ads/{ad_id}/enable")
    def dashboard_enable_ad(ad_id: int, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        _set_ad_enabled(ad_id, True)
        service.log_audit("ad_enable", actor_user_key="dashboard", detail=str(ad_id))
        return RedirectResponse("/dashboard/ads", status_code=303)

    @app.post("/dashboard/ads/{ad_id}/expiry")
    async def dashboard_update_ad_expiry(ad_id: int, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        active_until = _parse_active_until(form.get("active_until", ""))
        _set_ad_expiry(ad_id, active_until)
        service.log_audit("ad_expiry", actor_user_key="dashboard", detail=str(ad_id))
        return RedirectResponse("/dashboard/ads", status_code=303)

    @app.post("/dashboard/ads/{ad_id}/disable")
    def dashboard_disable_ad(ad_id: int, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        _set_ad_enabled(ad_id, False)
        service.log_audit("ad_disable", actor_user_key="dashboard", detail=str(ad_id))
        return RedirectResponse("/dashboard/ads", status_code=303)

    @app.post("/dashboard/ads/{ad_id}/delete")
    def dashboard_delete_ad(ad_id: int, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        _delete_ad(ad_id)
        service.log_audit("ad_delete", actor_user_key="dashboard", detail=str(ad_id))
        return RedirectResponse("/dashboard/ads", status_code=303)

    @app.post("/dashboard/users/{user_key}/ban")
    def dashboard_ban_user(user_key: str, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        service.set_banned(user_key, True, reason="dashboard", updated_by="dashboard")
        return RedirectResponse("/dashboard/bans", status_code=303)

    @app.post("/dashboard/users/{user_key}/unban")
    def dashboard_unban_user(user_key: str, request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        service.set_banned(user_key, False, updated_by="dashboard")
        return RedirectResponse("/dashboard/bans", status_code=303)

    @app.post("/dashboard/bans")
    async def dashboard_create_ban(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        service.set_banned(
            form.get("user_key", ""),
            True,
            reason=form.get("reason", "dashboard"),
            updated_by="dashboard",
        )
        return RedirectResponse("/dashboard/bans", status_code=303)

    @app.post("/dashboard/roles")
    async def dashboard_add_role(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        service.add_role(
            form.get("user_key", ""),
            form.get("role", ""),
            password=form.get("password", ""),
            added_by="dashboard",
        )
        return RedirectResponse("/dashboard/permissions", status_code=303)

    @app.post("/dashboard/roles/revoke")
    async def dashboard_revoke_role(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        service.revoke_role(form.get("user_key", ""), form.get("role", ""))
        service.log_audit(
            "role_revoke",
            actor_user_key="dashboard",
            target_user_key=form.get("user_key", ""),
            detail=form.get("role", ""),
        )
        return RedirectResponse("/dashboard/permissions", status_code=303)

    @app.post("/dashboard/resource-limits")
    async def dashboard_set_resource_limit(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        form = await _read_urlencoded_form(request)
        try:
            count = int(form.get("limit_count", "0"))
            if not 1 <= count <= 1000000:
                raise ValueError("invalid limit")
            service.set_resource_limit(
                form.get("resource", ""), count, form.get("window_unit", ""),
                updated_by="dashboard",
            )
        except (ValueError, TypeError):
            return HTMLResponse(_limits_page(service, {"view": "rules"}, error="请输入 1–1,000,000 之间的次数，并选择有效的资源和周期。", form=form), status_code=400)
        return RedirectResponse("/dashboard/limits?view=rules&saved=1", status_code=303)

    @app.post("/dashboard/resource-limits/reset-usage")
    def dashboard_reset_resource_usage(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        service.reset_resource_usage()
        service.log_audit("resource_usage_reset", actor_user_key="dashboard")
        return RedirectResponse("/dashboard/limits", status_code=303)

    return app


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _with_query_string(url: str, query: str) -> str:
    if not query:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{query}"


async def _forward_qq_webhook(
    body: bytes,
    headers: dict,
    forward_url: str,
) -> tuple[int, bytes, str]:
    headers = {key.lower(): value for key, value in headers.items()}
    request_headers = {
        "content-type": headers.get("content-type", "application/json"),
        "user-agent": headers.get("user-agent", ""),
        "x-bot-appid": headers.get("x-bot-appid", ""),
        "x-signature-timestamp": headers.get("x-signature-timestamp", ""),
        "x-signature-ed25519": headers.get("x-signature-ed25519", ""),
    }
    request_headers = {key: value for key, value in request_headers.items() if value}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                forward_url,
                content=body,
                headers=request_headers,
            )
        content_type = resp.headers.get("content-type", "application/json").split(";")[0]
        return resp.status_code, resp.content, content_type
    except Exception as e:
        payload = json.dumps(
            {"status": "error", "error": "qq_webhook_forward_failed", "detail": str(e)},
            ensure_ascii=False,
        ).encode("utf-8")
        return 502, payload, "application/json"


def _sign_dashboard_session(secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), b"admin", hashlib.sha256).hexdigest()
    return f"admin.{digest}"


def _dashboard_authenticated(request: Request, secret: str) -> bool:
    expected = _sign_dashboard_session(secret)
    actual = request.cookies.get("dashboard_session", "")
    return bool(secret) and hmac.compare_digest(actual, expected)


def _dashboard_auth_redirect(request: Request, secret: str):
    if not _dashboard_authenticated(request, secret):
        return RedirectResponse("/dashboard/login", status_code=303)
    return None


def _ai_settings_from_form(manager: AIConfigManager, form: dict[str, str]) -> AISettings:
    current = manager.load()
    return AISettings(
        base_url=str(form.get("base_url", "")).strip() or current.base_url,
        model=str(form.get("model", "")).strip() or current.model,
        api_key=str(form.get("api_key", "")).strip() or current.api_key,
    )


def _image_ai_settings_from_form(
    manager: ImageAIConfigManager, form: dict[str, str]
) -> ImageAISettings:
    current = manager.load()
    try:
        cooldown_seconds = int(
            str(form.get("cooldown_seconds", current.cooldown_seconds)).strip()
        )
    except (TypeError, ValueError):
        cooldown_seconds = -1
    return ImageAISettings(
        enabled=form.get("enabled", "") == "1",
        base_url=str(form.get("base_url", "")).strip() or current.base_url,
        model=str(form.get("model", "")).strip() or current.model,
        api_key=str(form.get("api_key", "")).strip() or current.api_key,
        size=str(form.get("size", "")).strip() or current.size,
        cooldown_seconds=cooldown_seconds,
    )


def _ai_page(
    manager: AIConfigManager,
    *,
    notice: str = "",
    error: str = "",
    base_url: str = "",
    model: str = "",
) -> str:
    public = manager.public_settings()
    visible_base_url = base_url or str(public["base_url"])
    visible_model = model or str(public["model"])
    key_status = (
        f"已配置：{public['api_key_masked']}"
        if public["api_key_configured"]
        else "尚未配置"
    )
    notice_html = (
        f"<div class='notice success' role='status' aria-live='polite'>{html.escape(notice)}</div>"
        if notice
        else ""
    )
    error_html = (
        f"<div class='notice error' role='alert' aria-live='assertive'>{html.escape(error)}</div>"
        if error
        else ""
    )
    body = f"""
    <section class="grid ai-page">
      <div class="panel span-2">
        <div class="panel-head"><h2>AI 对话配置</h2><span>仅管理员可修改，保存后立即重启 Bot</span></div>
        {notice_html}{error_html}
        <form class="stack-form ai-form" method="post" action="/dashboard/ai/test">
          <label for="ai-base-url">API 地址</label>
          <input id="ai-base-url" name="base_url" type="url" value="{html.escape(visible_base_url)}" required>
          <p class="field-note">填写 OpenAI 兼容接口的 v1 地址，例如 https://example.com/v1</p>
          <label for="ai-api-key">API Key</label>
          <input id="ai-api-key" name="api_key" type="password" autocomplete="new-password" placeholder="留空保持当前 Key">
          <p class="field-note">当前状态：{html.escape(key_status)}；页面不会回显完整 Key</p>
          <label for="ai-model">模型名称</label>
          <input id="ai-model" name="model" value="{html.escape(visible_model)}" required>
          <div class="actions ai-actions">
            <button type="submit" class="ghost">检测连接</button>
            <button type="submit" formaction="/dashboard/ai/save">保存并重启</button>
          </div>
        </form>
      </div>
      <div class="panel span-2 ai-guide">
        <div class="panel-head"><h2>生效规则</h2><span>变更可追溯</span></div>
        <div class="settings-list">
          <div><span>检测连接</span><strong>只检测，不修改当前配置</strong></div>
          <div><span>保存并重启</span><strong>检测通过后更新配置并重启机器人</strong></div>
          <div><span>重启失败</span><strong>自动恢复旧配置，不重启控制台</strong></div>
        </div>
      </div>
    </section>
    """
    return _layout("AI 对话", "ai", body)


def _image_ai_page(
    manager: ImageAIConfigManager,
    *,
    notice: str = "",
    error: str = "",
    settings: ImageAISettings | None = None,
    preview=None,
) -> str:
    public = manager.public_settings()
    current = settings or manager.load()
    key_status = (
        f"已配置：{public['api_key_masked']}"
        if public["api_key_configured"]
        else "尚未配置"
    )
    notice_html = (
        f"<div class='notice success' role='status' aria-live='polite'>{html.escape(notice)}</div>"
        if notice
        else ""
    )
    error_html = (
        f"<div class='notice error' role='alert' aria-live='assertive'>{html.escape(error)}</div>"
        if error
        else ""
    )
    checked = " checked" if current.enabled else ""
    size_options = "".join(
        f'<option value="{html.escape(size)}"'
        f'{" selected" if size == current.size else ""}>{html.escape(size)}</option>'
        for size in IMAGE_SIZES
    )
    preview_html = ""
    if preview:
        if getattr(preview, "url", ""):
            preview_src = html.escape(str(preview.url), quote=True)
        elif getattr(preview, "b64_json", ""):
            preview_src = "data:image/png;base64," + html.escape(
                str(preview.b64_json), quote=True
            )
        else:
            preview_src = ""
        if preview_src:
            preview_html = f"""
            <div class="image-ai-preview" aria-live="polite">
              <span>检测结果</span>
              <img src="{preview_src}" alt="AI 生图接口检测结果">
            </div>"""

    body = f"""
    <section class="grid ai-page">
      <div class="panel span-2">
        <div class="panel-head"><h2>AI 生图配置</h2><span>独立于 AI 对话，保存后立即重启 Bot</span></div>
        {notice_html}{error_html}
        <form class="stack-form ai-form" method="post" action="/dashboard/image-ai/test">
          <label class="toggle-field" for="image-ai-enabled">
            <input id="image-ai-enabled" name="enabled" type="checkbox" value="1"{checked}>
            <span><strong>启用 AI 生图</strong><small>关闭后生图请求不会调用外部接口</small></span>
          </label>
          <label for="image-ai-base-url">API 地址</label>
          <input id="image-ai-base-url" name="base_url" type="url" value="{html.escape(current.base_url, quote=True)}" placeholder="https://example.com/v1">
          <p class="field-note">填写 OpenAI 兼容接口的 v1 地址，系统请求 /images/generations</p>
          <label for="image-ai-api-key">API Key</label>
          <input id="image-ai-api-key" name="api_key" type="password" autocomplete="new-password" placeholder="留空保持当前 Key">
          <p class="field-note">当前状态：{html.escape(key_status)}；页面不会回显完整 Key</p>
          <label for="image-ai-model">生图模型</label>
          <input id="image-ai-model" name="model" value="{html.escape(current.model, quote=True)}" placeholder="grok-imagine-1.0-fast">
          <div class="form-grid-2">
            <div>
              <label for="image-ai-size">图片尺寸</label>
              <select id="image-ai-size" name="size">{size_options}</select>
            </div>
            <div>
              <label for="image-ai-cooldown">用户冷却（秒）</label>
              <input id="image-ai-cooldown" name="cooldown_seconds" type="number" min="0" max="86400" value="{current.cooldown_seconds}" required>
            </div>
          </div>
          <div class="actions ai-actions">
            <button type="submit" class="ghost">检测生图</button>
            <button type="submit" formaction="/dashboard/image-ai/save">保存并重启</button>
          </div>
        </form>
        {preview_html}
      </div>
      <div class="panel span-2 ai-guide">
        <div class="panel-head"><h2>生效规则</h2><span>群聊与私聊统一控制</span></div>
        <div class="settings-list">
          <div><span>触发方式</span><strong>/生图 描述，或“帮我画一张……”</strong></div>
          <div><span>检测生图</span><strong>真实生成一张测试图，不保存配置</strong></div>
          <div><span>用户冷却</span><strong>同一用户在群聊与私聊共用计时</strong></div>
          <div><span>重启失败</span><strong>自动恢复旧配置，不重启控制台</strong></div>
        </div>
      </div>
    </section>
    """
    return _layout("AI 生图", "image-ai", body)


def _login_html(error: str = "") -> str:
    return render_login(error)


def _overview_page(service: ControlService) -> str:
    users = _list_all_users(service)
    roles = service.list_roles()
    counts = _counts(users, roles)
    stats = service.list_resource_usage_stats()
    total = sum(item["counts"]["day"] for item in stats)
    recent = service.list_command_logs(limit=6)
    recent_html = "".join(
        f'<div class="mc-activity-item"><div><strong>{html.escape(item.get("command", ""))}</strong><time>{html.escape(usage_ui.short_time(item.get("created_at", "")))}</time></div><code>{html.escape(item.get("user_key", ""))}</code></div>'
        for item in recent
    ) or '<div class="empty">还没有新活动<span class="cell-note">机器人收到指令后，记录将显示在这里。</span></div>'
    body = f"""
    <section class="mc-overview-stats" aria-label="使用概况">
      {_metric("近 24 小时获取", total, "全部资源 · 次")}
      {_metric("用户总数", counts["users"], f"已记录 {counts['users']} 个 OpenID")}
      {_metric("管理成员", counts["admins"] + counts["staff"], f"管理员 {counts['admins']} · Staff {counts['staff']}")}
    </section>
    <section class="mc-overview-grid">
      <div class="panel"><div class="panel-head"><h2>资源使用</h2><a href="/dashboard/limits?view=rules">管理限制</a></div>{usage_ui.resource_list(stats)}</div>
      <div class="panel mc-activity"><div class="panel-head"><h2>最近活动</h2><a href="/dashboard/logs">查看全部</a></div>{recent_html}</div>
    </section>
    """
    return _layout("控制台", "overview", body)


def _ads_page(service: ControlService) -> str:
    ads = _read_ads()
    body = f"""
    <section class="panel">
      <details class="mc-add-record"><summary>新增广告</summary>

        <form class="stack-form" method="post" action="/dashboard/ads">
          <label>广告内容</label>
          <textarea name="content" placeholder="输入要追加到机器人回复底部的广告内容"></textarea>
          <label>到期时间（北京时间，可空=长期）</label>
          <input type="datetime-local" name="active_until" step="1">
          <label class="check"><input type="checkbox" name="enabled" value="1"> 新增后立即展示</label>
          <button type="submit" class="primary wide-btn">保存广告</button>
        </form>
      </details>
      <p class="field-note">共 {len(ads):,} 条广告</p>
      {_ads_table(ads)}
    </section>
    """
    return _layout("广告管理", "ads", body)


def _users_page(service: ControlService) -> str:
    users = _list_all_users(service)
    enriched = [service.get_user_state(item["user_key"]) | item for item in users]
    body = f"""
    <section class="panel">
      <p class="mc-list-caption">共 {len(enriched):,} 位用户 · 绑定邮箱与当前状态</p>
      {_users_table(enriched)}
    </section>
    """
    return _layout("用户列表", "users", body)


def _permissions_page(service: ControlService) -> str:
    roles = service.list_roles()
    body = f"""
    <section class="panel">
      <details class="mc-add-record"><summary>授予权限</summary>{_role_form()}</details>
      <p class="mc-list-caption">共 {len(roles):,} 条授权 · 管理员 / Staff</p>
      {_roles_table(roles)}
    </section>
    """
    return _layout("权限管理", "permissions", body)


def _bans_page(service: ControlService) -> str:
    users = _list_all_users(service)
    banned = [item for item in users if item["is_banned"]]
    body = f"""
    <section class="panel">
      <details class="mc-add-record"><summary>封禁用户</summary>{_ban_form()}</details>
      <p class="mc-list-caption">共 {len(banned):,} 位受限用户</p>
      {_bans_table(banned)}
    </section>
    """
    return _layout("封禁名单", "bans", body)


def _limits_page(service: ControlService, params=None, error: str = "", form=None) -> str:
    params = params or {}
    resource = str(params.get("resource", ""))
    if resource not in {"163", "4399", "nfa"}:
        resource = ""
    query = str(params.get("q", ""))[:128].strip()
    try:
        page = max(1, int(params.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    rules_view = params.get("view") == "rules"
    now = datetime.now(timezone.utc)
    stats = service.list_resource_usage_stats(now=now)
    notices = f'<div class="notice error" role="alert">{html.escape(error)}</div>' if error else ""
    if params.get("saved") == "1":
        notices += '<div class="notice success" role="status">限制规则已保存，对所有群和私聊生效。</div>'
    tabs = '<nav class="mc-tabs" aria-label="获取限制视图">' + ''.join(
        f'<a href="{url}" class="{ "is-active" if active else ""}"' + (' aria-current="page"' if active else '') + f'>{label}</a>'
        for url, label, active in [("/dashboard/limits", "用户用量", not rules_view), ("/dashboard/limits?view=rules", "限制规则", rules_view)]
    ) + '</nav>'
    if rules_view:
        content = f'''<section class="panel">
          <div class="panel-head"><div><h2>限制规则</h2><p>选择资源以修改个人额度。已有获取记录会继续计入。</p></div></div>
          {usage_ui.rule_list(stats, form)}
          <p class="field-note">限额在群聊与私聊间共用，按滚动周期释放。</p>
          <details class="mc-reset"><summary>重置获取记录</summary>
            <p>将清空所有资源的用量历史，所有用户重新获得额度。此操作不可撤销。</p>
            <form method="post" action="/dashboard/resource-limits/reset-usage" data-confirm="确定清空全部资源的获取记录？所有用户额度会重置，此操作不可撤销。"><button class="danger">重置全部记录</button></form>
          </details>
        </section>'''
    else:
        users = service.list_resource_user_usage(resource=resource, query=query, page=page, now=now)
        refresh = html.escape(urlencode({"resource": resource, "q": query, "page": page}))
        content = f'''<section class="panel" id="user-usage">
          <div class="mc-toolbar-title"><div><h2>用户用量明细</h2><span>{users['total']:,} 条有效用量</span></div><a class="button ghost" href="/dashboard/limits?{refresh}">刷新数据</a></div>
          {usage_ui.filters(resource, query)}
          {usage_ui.user_usage_table(users)}
          {usage_ui.pagination(users, resource, query)}
          <p class="field-note">按个人滚动周期统计，群聊与私聊共用额度。下次释放是最早一条记录释放的时间，并非全部额度重置。</p>
        </section>
        <details class="mc-disclosure"><summary>资源用量总览<span>查看各时间窗口的全体获取次数</span></summary>
          {usage_ui.usage_summary(stats)}
          <p class="field-note">滚动窗口互有重叠，不能相加；全体次数不代表个人已用额度。</p>
        </details>'''
    return _layout("获取限制", "limits", notices + tabs + content)


def _logs_page(service: ControlService, params=None) -> str:
    selected = (params or {}).get("view", "commands")
    views = {
        "commands": ("命令记录", service.list_command_logs, ["created_at", "user_key", "command", "content"]),
        "outbound": ("发送记录", service.list_outbound_logs, ["created_at", "user_key", "channel", "status", "content"]),
        "audit": ("管理操作", service.list_audit_logs, ["created_at", "actor_user_key", "action", "target_user_key", "detail"]),
    }
    if selected not in views:
        selected = "commands"
    tabs = '<nav class="mc-tabs" aria-label="日志类型">' + ''.join(
        f'<a href="/dashboard/logs?view={key}" class="{ "is-active" if key == selected else ""}"' + (' aria-current="page"' if key == selected else '') + f'>{value[0]}</a>'
        for key, value in views.items()
    ) + '</nav>'
    label, load, columns = views[selected]
    body = tabs + f'<section class="panel"><div class="panel-head"><h2>{label}</h2><span>最近 50 条</span></div>{_logs_table(load(limit=50), columns)}</section>'
    return _layout("日志审计", "logs", body)


def _settings_page(service: ControlService) -> str:
    _ = service
    body = f"""
    <section class="grid">
      <div class="panel">
        <div class="panel-head"><h2>系统设置</h2><span>运行接入</span></div>
        {_settings_panel()}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>数据来源</h2><span>当前配置</span></div>
        {_data_source_panel()}
      </div>
    </section>
    """
    return _layout("系统设置", "settings", body)


def _layout(title: str, active: str, body: str) -> str:
    return render_layout(title, active, body)


def _counts(users: list[dict], roles: list[dict]) -> dict:
    return {
        "users": len(users),
        "admins": len([r for r in roles if r["role"] == "admin"]),
        "staff": len([r for r in roles if r["role"] == "staff"]),
        "banned": len([u for u in users if u["is_banned"]]),
    }


def _list_all_users(service: ControlService) -> list[dict]:
    return service.list_users(limit=None)


def _metric(label: str, value: int, note: str = "") -> str:
    return f"<div class='metric'><span>{html.escape(label)}</span><strong>{value:,}</strong><small>{html.escape(note)}</small></div>"


def _users_table(users: list[dict]) -> str:
    rows = []
    for user in users:
        user_key = user["user_key"]
        state = "已封禁" if user["is_banned"] else "正常"
        roles = " / ".join(_role_label(role) for role in user.get("roles", [])) or "-"
        action = "unban" if user["is_banned"] else "ban"
        label = "解封" if user["is_banned"] else "封禁"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(user_key)}</code></td>"
            f"<td>{html.escape(user.get('email', '')) or '-'}</td>"
            f"<td><span class='chip'>{state}</span></td>"
            f"<td>{html.escape(roles)}</td>"
            f"<td>{html.escape(user.get('last_group_openid', '')) or '-'}</td>"
            f"<td><form method='post' action='/dashboard/users/{html.escape(user_key)}/{action}'><button>{label}</button></form></td>"
            "</tr>"
        )
    return _table(["OpenID", "绑定邮箱", "状态", "权限", "最近群", "操作"], rows)


def _bans_table(users: list[dict]) -> str:
    rows = []
    for user in users:
        user_key = user["user_key"]
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(user_key)}</code></td>"
            f"<td>{html.escape(user.get('banned_reason', '')) or '-'}</td>"
            f"<td>{html.escape(user.get('last_seen_at', '')[:19])}</td>"
            f"<td><form method='post' action='/dashboard/users/{html.escape(user_key)}/unban'><button>解封</button></form></td>"
            "</tr>"
        )
    return _table(["OpenID", "原因", "最近记录", "操作"], rows)


def _roles_table(roles: list[dict]) -> str:
    rows = []
    for item in roles:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(item['user_key'])}</code></td>"
            f"<td><span class='chip'>{_role_label(item['role'])}</span></td>"
            f"<td>{html.escape(item.get('added_by', '')) or '-'}</td>"
            "<td>"
            "<form method='post' action='/dashboard/roles/revoke'>"
            f"<input type='hidden' name='user_key' value='{html.escape(item['user_key'])}'>"
            f"<input type='hidden' name='role' value='{html.escape(item['role'])}'>"
            "<button>撤销</button></form>"
            "</td>"
            "</tr>"
        )
    return _table(["OpenID", "权限", "来源", "操作"], rows)


def _ads_table(ads: list[dict]) -> str:
    rows = []
    for ad in ads:
        ad_id = int(ad.get("id", 0) or 0)
        enabled = bool(ad.get("enabled"))
        state = "展示中" if enabled else "未展示"
        action = "disable" if enabled else "enable"
        label = "停止展示" if enabled else "开始展示"
        until = _format_active_until(ad.get("active_until"))
        until_value = _active_until_input_value(ad.get("active_until"))
        current_text = until if until else "未开通"
        rows.append(
            "<tr>"
            f"<td>{ad_id}</td>"
            f"<td class='long-text'>{html.escape(str(ad.get('content', '')))}</td>"
            f"<td><span class='chip'>{state}</span></td>"
            "<td>"
            f"<form class='expiry-form' method='post' action='/dashboard/ads/{ad_id}/expiry'>"
            "<div class='expiry-row'>"
            f"<input type='datetime-local' name='active_until' aria-label='广告到期时间（北京时间）' step='1' value='{html.escape(until_value)}'>"
            "<button>保存</button>"
            "</div>"
            f"<div class='expiry-current'>当前：{html.escape(current_text)}</div>"
            "</form>"
            "</td>"
            f"<td>{html.escape(str(ad.get('created_at', '')))}</td>"
            "<td class='actions'>"
            f"<form method='post' action='/dashboard/ads/{ad_id}/{action}'><button>{label}</button></form>"
            f"<form method='post' action='/dashboard/ads/{ad_id}/delete'><button class='danger'>删除</button></form>"
            "</td>"
            "</tr>"
        )
    return _table(["ID", "内容", "状态", "月费到期", "创建时间", "操作"], rows)


def _logs_table(items: list[dict], columns: list[str]) -> str:
    labels = {
        "created_at": "时间",
        "user_key": "用户",
        "command": "指令",
        "content": "内容",
        "actor_user_key": "操作人",
        "action": "动作",
        "target_user_key": "目标用户",
        "detail": "详情",
        "channel": "渠道",
        "status": "状态",
    }
    rows = []
    for item in items:
        cells = "".join(
            f"<td>{html.escape(str(item.get(col, ''))[:180])}</td>" for col in columns
        )
        rows.append(f"<tr>{cells}</tr>")
    return _table([labels.get(col, col) for col in columns], rows)


def _table(headers: list[str], rows: list[str], numeric: set[int] | None = None) -> str:
    head = "".join(f"<th scope='col' class='{'numeric' if index in (numeric or set()) else ''}'>{html.escape(item)}</th>" for index, item in enumerate(headers))
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}' class='empty'>暂无数据</td></tr>"
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _role_form() -> str:
    return """
<form class="stack-form" method="post" action="/dashboard/roles">
  <label>OpenID</label>
  <input name="user_key" placeholder="用户 openid">
  <label>权限</label>
  <select name="role"><option value="staff">Staff</option><option value="admin">管理员</option></select>
  <label>Staff 密码</label>
  <input name="password" placeholder="仅 Staff 需要，可空">
  <button>授予权限</button>
</form>"""


def _ban_form() -> str:
    return """
<form class="stack-form" method="post" action="/dashboard/bans">
  <label>OpenID</label>
  <input name="user_key" placeholder="要封禁的 openid">
  <label>原因</label>
  <input name="reason" placeholder="可空">
  <button>封禁 OpenID</button>
</form>"""


def _settings_panel() -> str:
    ws_enabled = "开启" if os.getenv("QQ_OFFICIAL_WS_ENABLED", "") == "1" else "关闭"
    bridge_enabled = "开启" if os.getenv("QQ_BRIDGE_ENABLED", "") == "1" else "关闭"
    bot_type = os.getenv("QQ_BOT_TYPE", "public")
    return f"""
<div class="settings-list">
  <div><span>QQ 官方 WebSocket</span><strong>{ws_enabled}</strong></div>
  <div><span>桥接监听</span><strong>{bridge_enabled}</strong></div>
  <div><span>Bot 类型</span><strong>{html.escape(bot_type)}</strong></div>
  <div><span>控制 API</span><strong>{html.escape(os.getenv("CONTROL_API_HOST", "127.0.0.1"))}:{html.escape(os.getenv("CONTROL_API_PORT", "9000"))}</strong></div>
</div>"""


def _data_source_panel() -> str:
    database_url = os.getenv("DATABASE_URL", "data/control.db")
    local_state = str(_local_state_dir())
    safe_db = database_url.split("@")[-1] if "@" in database_url else database_url
    return f"""
<div class="settings-list">
  <div><span>数据库</span><strong>{html.escape(safe_db)}</strong></div>
  <div><span>本地数据目录</span><strong>{html.escape(local_state)}</strong></div>
  <div><span>广告文件</span><strong>{html.escape(str(_ads_file()))}</strong></div>
  <div><span>登录密钥</span><strong>ADMIN_CONTROL_TOKEN</strong></div>
</div>"""


def _role_label(role: str) -> str:
    return {"admin": "管理员", "staff": "Staff"}.get(role, role)


def _unit_label(unit: str) -> str:
    return {
        "min": "分钟",
        "hour": "小时",
        "day": "天",
        "month": "月",
        "quarter": "季度",
        "year": "年",
    }.get(unit, unit)


def _format_active_until(value) -> str:
    if value in (None, ""):
        return "长期"
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(
            BEIJING_TZ
        ).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def _active_until_input_value(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(
            BEIJING_TZ
        ).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def _parse_active_until(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=BEIJING_TZ)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def _local_state_dir() -> Path:
    root = os.getenv("LOCAL_STATE_DIR", "")
    if root:
        return Path(root)
    return Path(__file__).resolve().parent.parent / "data"


def _ads_file() -> Path:
    return _local_state_dir() / "ads.json"


def _read_ads() -> list[dict]:
    path = _ads_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    ads = [item for item in data if isinstance(item, dict) and item.get("content")]
    if _expire_ads(ads):
        _write_ads(ads)
    return ads


def _write_ads(ads: list[dict]) -> None:
    path = _ads_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ads, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_ad(content: str, enabled: bool, active_until=None) -> None:
    content = str(content or "").strip()
    if not content:
        return
    ads = _read_ads()
    new_id = max((int(ad.get("id", 0) or 0) for ad in ads), default=0) + 1
    ads.append(
        {
            "id": new_id,
            "content": content,
            "enabled": bool(enabled),
            "active_until": active_until,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    _write_ads(ads)


def _set_ad_enabled(ad_id: int, enabled: bool) -> None:
    ads = _read_ads()
    for ad in ads:
        if int(ad.get("id", 0) or 0) == int(ad_id):
            ad["enabled"] = bool(enabled)
            if enabled:
                ad["active_until"] = None
            else:
                ad["active_until"] = None
            break
    _write_ads(ads)


def _set_ad_expiry(ad_id: int, active_until) -> None:
    ads = _read_ads()
    for ad in ads:
        if int(ad.get("id", 0) or 0) == int(ad_id):
            ad["active_until"] = active_until
            if isinstance(active_until, (int, float)) and active_until <= time.time():
                ad["enabled"] = False
            break
    _write_ads(ads)


def _expire_ads(ads: list[dict]) -> bool:
    now = time.time()
    changed = False
    for ad in ads:
        until = ad.get("active_until")
        if ad.get("enabled") and isinstance(until, (int, float)) and until <= now:
            ad["enabled"] = False
            changed = True
    return changed


def _delete_ad(ad_id: int) -> None:
    ads = [ad for ad in _read_ads() if int(ad.get("id", 0) or 0) != int(ad_id)]
    _write_ads(ads)



app = create_app(
    database_url=os.getenv("DATABASE_URL", ""),
    bot_token=os.getenv("BOT_CONTROL_TOKEN", ""),
    admin_token=os.getenv("ADMIN_CONTROL_TOKEN", ""),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "control_api.app:app",
        host=os.getenv("CONTROL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("CONTROL_API_PORT", "9000")),
        reload=False,
    )
