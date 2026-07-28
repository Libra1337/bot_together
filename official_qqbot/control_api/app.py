import hashlib
import hmac
import html
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .auth import require_admin_token, require_bot_token
from .db import create_app_engine, init_db
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


def create_app(database_url: str, bot_token: str, admin_token: str) -> FastAPI:
    engine = create_app_engine(database_url)
    init_db(engine)
    service = ControlService(engine)
    app = FastAPI(title="Official QQBot Control API")
    app.state.engine = engine
    app.state.control_service = service

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
        return HTMLResponse(_limits_page(service))

    @app.get("/dashboard/logs", response_class=HTMLResponse)
    def dashboard_logs(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_logs_page(service))

    @app.get("/dashboard/settings", response_class=HTMLResponse)
    def dashboard_settings(request: Request):
        auth = _dashboard_auth_redirect(request, dashboard_secret)
        if auth:
            return auth
        return HTMLResponse(_settings_page(service))

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
        service.set_resource_limit(
            form.get("resource", ""),
            int(form.get("limit_count", "0")),
            form.get("window_unit", ""),
            updated_by="dashboard",
        )
        return RedirectResponse("/dashboard/limits", status_code=303)

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
    request_headers = {
        "content-type": headers.get("content-type", "application/json"),
        "user-agent": headers.get("user-agent", ""),
        "x-bot-appid": headers.get("x-bot-appid", ""),
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


def _login_html(error: str = "") -> str:
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Miracle 控制台登录</title>
  <style>{_DASHBOARD_CSS}</style>
</head>
<body class="login-body">
  <main class="login-panel">
    <div class="brand-line">MIRACLE BOT</div>
    <h1>控制台登录</h1>
    <form method="post" action="/dashboard/login">
      <label>管理密钥</label>
      <input name="token" type="password" autocomplete="current-password" autofocus>
      <button type="submit">登录</button>
    </form>
    {error_html}
  </main>
</body>
</html>"""


def _overview_page(service: ControlService) -> str:
    users = _list_all_users(service)
    roles = service.list_roles()
    limits = service.list_resource_limits()
    ads = _read_ads()
    counts = _counts(users, roles)
    body = f"""
    <section class="metrics">
      {_metric("用户", counts["users"])}
      {_metric("管理员", counts["admins"])}
      {_metric("Staff", counts["staff"])}
      {_metric("封禁", counts["banned"])}
    </section>
    <section class="grid">
      {_quick_card("广告管理", f"共 {len(ads)} 条，启用 {len([a for a in ads if a.get('enabled')])} 条", "/dashboard/ads")}
      {_quick_card("用户列表", f"已记录 {counts['users']} 个 OpenID", "/dashboard/users")}
      {_quick_card("获取限制", f"当前 {len(limits)} 条限制规则", "/dashboard/limits")}
      {_quick_card("日志审计", "查看命令、发送、权限变更记录", "/dashboard/logs")}
    </section>
    """
    return _layout("控制台", "overview", body)


def _ads_page(service: ControlService) -> str:
    ads = _read_ads()
    body = f"""
    <section class="split">
      <div class="panel">
        <div class="panel-head"><h2>新增广告</h2><span>对应 Bot 的 /ad+ /ads+</span></div>
        <form class="stack-form" method="post" action="/dashboard/ads">
          <label>广告内容</label>
          <textarea name="content" placeholder="输入要追加到机器人回复底部的广告内容"></textarea>
          <label>到期时间（北京时间，可空=长期）</label>
          <input type="datetime-local" name="active_until" step="1">
          <label class="check"><input type="checkbox" name="enabled" value="1"> 新增后立即展示</label>
          <button type="submit" class="primary wide-btn">保存广告</button>
        </form>
      </div>
      <div class="panel wide">
        <div class="panel-head"><h2>广告列表</h2><span>读取 data/ads.json</span></div>
        {_ads_table(ads)}
      </div>
    </section>
    """
    return _layout("广告管理", "ads", body)


def _users_page(service: ControlService) -> str:
    users = _list_all_users(service)
    enriched = [service.get_user_state(item["user_key"]) | item for item in users]
    body = f"""
    <section class="panel">
      <div class="panel-head"><h2>用户列表</h2><span>OpenID / 绑定邮箱 / 状态</span></div>
      {_users_table(enriched)}
    </section>
    """
    return _layout("用户列表", "users", body)


def _permissions_page(service: ControlService) -> str:
    roles = service.list_roles()
    body = f"""
    <section class="grid">
      <div class="panel">
        <div class="panel-head"><h2>权限管理</h2><span>管理员 / Staff</span></div>
        {_roles_table(roles)}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>授予权限</h2><span>写入云端数据库</span></div>
        {_role_form()}
      </div>
    </section>
    """
    return _layout("权限管理", "permissions", body)


def _bans_page(service: ControlService) -> str:
    users = _list_all_users(service)
    banned = [item for item in users if item["is_banned"]]
    body = f"""
    <section class="grid">
      <div class="panel">
        <div class="panel-head"><h2>封禁名单</h2><span>已封禁 OpenID</span></div>
        {_bans_table(banned)}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>封禁 OpenID</h2><span>立即生效</span></div>
        {_ban_form()}
      </div>
    </section>
    """
    return _layout("封禁名单", "bans", body)


def _limits_page(service: ControlService) -> str:
    limits = service.list_resource_limits()
    stats = service.list_resource_usage_stats()
    body = f"""
    <section class="grid">
      <div class="panel">
        <div class="panel-head"><h2>获取限制</h2><span>所有群全局生效</span></div>
        {_limits_table(limits)}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>设置限制</h2><span>/restrict 163/4399/nfa 数量 时间</span></div>
        {_limit_form()}
      </div>
      <div class="panel span-2">
        <div class="panel-head"><h2>实时获取统计</h2><span>秒 / 分钟 / 小时 / 天 / 月 / 年</span></div>
        {_usage_charts(stats)}
      </div>
    </section>
    """
    return _layout("获取限制", "limits", body)


def _logs_page(service: ControlService) -> str:
    command_logs = service.list_command_logs(limit=50)
    audit_logs = service.list_audit_logs(limit=50)
    outbound_logs = service.list_outbound_logs(limit=50)
    body = f"""
    <section class="grid">
      <div class="panel">
        <div class="panel-head"><h2>命令日志</h2><span>最近 50 条</span></div>
        {_logs_table(command_logs, ["created_at", "user_key", "command", "content"])}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>审计日志</h2><span>权限 / 封禁 / 广告</span></div>
        {_logs_table(audit_logs, ["created_at", "actor_user_key", "action", "target_user_key", "detail"])}
      </div>
      <div class="panel span-2">
        <div class="panel-head"><h2>发送日志</h2><span>邮件 / 消息</span></div>
        {_logs_table(outbound_logs, ["created_at", "user_key", "channel", "status", "content"])}
      </div>
    </section>
    """
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
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Miracle Bot {html.escape(title)}</title>
  <style>{_DASHBOARD_CSS}</style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand"><span class="brand-dot"></span>MIRACLE</div>
    <nav>
      {_nav_link("overview", "/dashboard", "控制台", active)}
      {_nav_link("ads", "/dashboard/ads", "广告管理", active)}
      {_nav_link("users", "/dashboard/users", "用户列表", active)}
      {_nav_link("permissions", "/dashboard/permissions", "权限管理", active)}
      {_nav_link("bans", "/dashboard/bans", "封禁名单", active)}
      {_nav_link("limits", "/dashboard/limits", "获取限制", active)}
      {_nav_link("logs", "/dashboard/logs", "日志审计", active)}
      {_nav_link("settings", "/dashboard/settings", "系统设置", active)}
    </nav>
  </aside>
  <main class="console">
    <header class="page-head">
      <div>
        <p class="eyebrow">CONTROL CONSOLE</p>
        <h1>{html.escape(title)}</h1>
      </div>
      <div class="status">云端同步</div>
      <form method="post" action="/dashboard/logout"><button class="ghost">退出登录</button></form>
    </header>
    {body}
  </main>
  <script>{_DASHBOARD_JS}</script>
</body>
</html>"""


def _nav_link(key: str, href: str, label: str, active: str) -> str:
    klass = "active" if key == active else ""
    return f'<a class="{klass}" href="{href}">{html.escape(label)}</a>'


def _counts(users: list[dict], roles: list[dict]) -> dict:
    return {
        "users": len(users),
        "admins": len([r for r in roles if r["role"] == "admin"]),
        "staff": len([r for r in roles if r["role"] == "staff"]),
        "banned": len([u for u in users if u["is_banned"]]),
    }


def _list_all_users(service: ControlService) -> list[dict]:
    return service.list_users(limit=None)


def _metric(label: str, value: int) -> str:
    return f"<div class='metric'><span>{html.escape(label)}</span><strong>{value}</strong></div>"


def _quick_card(title: str, subtitle: str, href: str) -> str:
    return (
        "<a class='quick-card' href='"
        + html.escape(href)
        + "'>"
        + f"<h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p>"
        + "</a>"
    )


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


def _limits_table(limits: list[dict]) -> str:
    rows = [
        "<tr>"
        f"<td>{html.escape(item['resource'])}</td>"
        f"<td>{item['limit_count']}</td>"
        f"<td>{_unit_label(item['window_unit'])}</td>"
        f"<td>{item['window_seconds']} 秒</td>"
        f"<td>{html.escape(item.get('updated_by', '')) or '-'}</td>"
        "</tr>"
        for item in limits
    ]
    return _table(["资源", "数量", "周期", "秒数", "更新人"], rows)


def _usage_charts(stats: list[dict]) -> str:
    if not stats:
        return "<div class='empty'>暂无获取记录</div>"
    labels = [
        ("second", "秒"),
        ("minute", "分钟"),
        ("hour", "小时"),
        ("day", "天"),
        ("month", "月"),
        ("year", "年"),
    ]
    cards = []
    for item in stats:
        counts = item.get("counts", {}) or {}
        values = [int(counts.get(key, 0) or 0) for key, _ in labels]
        max_value = max(values + [1])
        resource = html.escape(str(item["resource"]))
        cards.append(
            "<article class='usage-card'>"
            "<div class='usage-card-head'>"
            f"<strong>{resource}</strong>"
            f"<span>上限 {int(item.get('limit_count', 0) or 0)} / {_unit_label(str(item.get('window_unit', '')))}</span>"
            "</div>"
            "<div class='chart-tabs' role='tablist' aria-label='图表类型'>"
            "<button type='button' class='chart-tab is-active' data-chart-type='line'>折线图</button>"
            "<button type='button' class='chart-tab' data-chart-type='pie'>饼状图</button>"
            "<button type='button' class='chart-tab' data-chart-type='radar'>雷达图</button>"
            "<button type='button' class='chart-tab' data-chart-type='bar'>柱状图</button>"
            "</div>"
            "<div class='usage-chart'>"
            f"{_line_chart(resource, labels, values, max_value)}"
            f"{_pie_chart(resource, labels, values)}"
            f"{_radar_chart(resource, labels, values, max_value)}"
            f"{_bar_chart(resource, labels, values, max_value)}"
            "</div>"
            "</article>"
        )
    return f"<div class='usage-grid'>{''.join(cards)}</div>"


def _line_chart(resource: str, labels: list[tuple[str, str]], values: list[int], max_value: int) -> str:
    width = 320
    height = 180
    left = 26
    top = 18
    chart_w = 268
    chart_h = 106
    points = []
    dots = []
    for idx, ((_, label), value) in enumerate(zip(labels, values)):
        x = left + (chart_w / (len(values) - 1)) * idx
        y = top + chart_h - (value / max_value * chart_h if max_value else 0)
        points.append(f"{x:.1f},{y:.1f}")
        tooltip = html.escape(f"{resource} {label}内获取 {value} 次")
        dots.append(
            f"<button type='button' class='chart-point' style='--point-x:{x / width * 100:.2f}%;--point-y:{y / height * 100:.2f}%' data-tooltip='{tooltip}' aria-label='{tooltip}'><span>{value}</span></button>"
        )
    x_labels = "".join(
        f"<text x='{left + (chart_w / (len(labels) - 1)) * idx:.1f}' y='160' text-anchor='middle'>{html.escape(label)}</text>"
        for idx, (_, label) in enumerate(labels)
    )
    return (
        "<div class='chart-pane is-active' data-chart-type='line'>"
        "<div class='chart-stage'>"
        f"<svg class='line-svg' viewBox='0 0 {width} {height}' role='img' aria-label='{resource} 折线图'>"
        "<line x1='26' y1='124' x2='294' y2='124' class='chart-axis' />"
        "<line x1='26' y1='18' x2='26' y2='124' class='chart-axis' />"
        f"<polyline points='{' '.join(points)}' class='chart-line' />"
        f"{x_labels}"
        "</svg>"
        f"{''.join(dots)}"
        "</div>"
        "</div>"
    )


def _pie_chart(resource: str, labels: list[tuple[str, str]], values: list[int]) -> str:
    total = sum(values)
    if total <= 0:
        total = 1
    colors = ["#2563eb", "#0f766e", "#7c3aed", "#ea580c", "#dc2626", "#475569"]
    gradient_parts = []
    cursor = 0.0
    legend = []
    for idx, ((_, label), value) in enumerate(zip(labels, values)):
        percent = value / total * 100
        start = cursor
        cursor += percent
        color = colors[idx % len(colors)]
        gradient_parts.append(f"{color} {start:.2f}% {cursor:.2f}%")
        tooltip = html.escape(f"{resource} {label}内获取 {value} 次")
        legend.append(
            f"<button type='button' class='pie-legend-item chart-hotspot' data-tooltip='{tooltip}' aria-label='{tooltip}'><span style='background:{color}'></span>{html.escape(label)} {value}</button>"
        )
    return (
        "<div class='chart-pane' data-chart-type='pie'>"
        "<div class='pie-layout'>"
        f"<div class='pie-visual' style='background: conic-gradient({', '.join(gradient_parts)})'></div>"
        f"<div class='pie-legend'>{''.join(legend)}</div>"
        "</div>"
        "</div>"
    )


def _radar_chart(resource: str, labels: list[tuple[str, str]], values: list[int], max_value: int) -> str:
    import math

    cx = 160
    cy = 88
    radius = 62
    axis_lines = []
    label_nodes = []
    points = []
    hotspots = []
    for idx, ((_, label), value) in enumerate(zip(labels, values)):
        angle = -math.pi / 2 + idx * (2 * math.pi / len(labels))
        outer_x = cx + math.cos(angle) * radius
        outer_y = cy + math.sin(angle) * radius
        axis_lines.append(f"<line x1='{cx}' y1='{cy}' x2='{outer_x:.1f}' y2='{outer_y:.1f}' class='radar-axis' />")
        label_x = cx + math.cos(angle) * (radius + 20)
        label_y = cy + math.sin(angle) * (radius + 20)
        label_nodes.append(f"<text x='{label_x:.1f}' y='{label_y:.1f}' text-anchor='middle'>{html.escape(label)}</text>")
        scaled = radius * (value / max_value if max_value else 0)
        x = cx + math.cos(angle) * scaled
        y = cy + math.sin(angle) * scaled
        points.append(f"{x:.1f},{y:.1f}")
        tooltip = html.escape(f"{resource} {label}内获取 {value} 次")
        hotspots.append(
            f"<button type='button' class='chart-point' style='--point-x:{x / 320 * 100:.2f}%;--point-y:{y / 180 * 100:.2f}%' data-tooltip='{tooltip}' aria-label='{tooltip}'><span>{value}</span></button>"
        )
    return (
        "<div class='chart-pane' data-chart-type='radar'>"
        "<div class='chart-stage'>"
        "<svg class='radar-svg' viewBox='0 0 320 180' role='img' aria-label='雷达图'>"
        "<circle cx='160' cy='88' r='62' class='radar-ring' />"
        "<circle cx='160' cy='88' r='38' class='radar-ring' />"
        f"{''.join(axis_lines)}"
        f"<polygon points='{' '.join(points)}' class='radar-area' />"
        f"{''.join(label_nodes)}"
        "</svg>"
        f"{''.join(hotspots)}"
        "</div>"
        "</div>"
    )


def _bar_chart(resource: str, labels: list[tuple[str, str]], values: list[int], max_value: int) -> str:
    bars = []
    for (_, label), value in zip(labels, values):
        height = max(8, round(value / max_value * 100)) if value else 6
        tooltip = html.escape(f"{resource} {label}内获取 {value} 次")
        bars.append(
            "<button type='button' class='usage-bar chart-hotspot' "
            f"style='--bar-height:{height}%' "
            f"data-tooltip='{tooltip}' "
            f"aria-label='{tooltip}'>"
            "<span class='usage-bar-fill'></span>"
            f"<span class='usage-value'>{value}</span>"
            f"<span class='usage-label'>{html.escape(label)}</span>"
            "</button>"
        )
    return (
        "<div class='chart-pane' data-chart-type='bar'>"
        f"<div class='bar-chart'>{''.join(bars)}</div>"
        "</div>"
    )


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
            f"<input type='datetime-local' name='active_until' step='1' value='{html.escape(until_value)}'>"
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


def _table(headers: list[str], rows: list[str]) -> str:
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}' class='empty'>暂无数据</td></tr>"
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _limit_form() -> str:
    return """
<form class="inline-form" method="post" action="/dashboard/resource-limits">
  <select name="resource"><option>163</option><option>4399</option><option>nfa</option></select>
  <input name="limit_count" type="number" min="1" value="1">
  <select name="window_unit"><option value="min">分钟</option><option value="hour">小时</option><option value="day">天</option><option value="month">月</option><option value="quarter">季度</option><option value="year">年</option></select>
  <button>设置限制</button>
</form>
<form class="inline-form" method="post" action="/dashboard/resource-limits/reset-usage">
  <button>重置获取记录</button>
</form>"""


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


_DASHBOARD_CSS = """
:root { color-scheme: light; font-family: Inter, Arial, "Microsoft YaHei", sans-serif; background: #f6f5f1; color: #111; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f5f1; }
button, input, select, textarea { font: inherit; }
.sidebar { position: fixed; inset: 0 auto 0 0; width: 220px; border-right: 1px solid #ddd8ce; background: #fbfaf7; padding: 22px 14px; }
.brand { display: flex; align-items: center; gap: 8px; height: 32px; color: #666; font-size: 13px; font-weight: 800; letter-spacing: .04em; margin-bottom: 28px; }
.brand-dot { width: 10px; height: 10px; border: 2px solid #666; border-radius: 50%; display: inline-block; transition: transform .22s ease, border-color .22s ease; }
.brand:hover .brand-dot { transform: scale(1.18); border-color: #111; }
nav { display: grid; gap: 7px; }
nav a { color: #111; text-decoration: none; padding: 11px 14px; border-radius: 8px; font-weight: 700; transition: background-color .18s ease, color .18s ease, transform .18s ease; }
nav a.active, nav a:hover { background: #050505; color: #fff; transform: translateX(2px); }
.console { margin-left: 220px; padding: 28px 32px 60px; animation: consoleEnter .32s ease-out both; }
.page-head { display: grid; grid-template-columns: 1fr auto auto; align-items: end; gap: 16px; margin-bottom: 20px; }
.eyebrow { margin: 0 0 6px; color: #777; font-size: 12px; font-weight: 800; letter-spacing: .08em; }
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
h2 { margin: 0; font-size: 18px; letter-spacing: 0; }
p { margin: 0; }
.status { color: #777; font-size: 13px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.metric, .panel, .quick-card { border: 1px solid #ddd8ce; background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 0 rgba(17,17,17,.03); transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
.metric:hover, .panel:hover, .quick-card:hover { transform: translateY(-2px); border-color: #cfc8ba; box-shadow: 0 12px 28px rgba(17,17,17,.08); }
.metric span { display: block; color: #777; font-size: 13px; }
.metric strong { display: block; margin-top: 8px; font-size: 26px; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }
.split { display: grid; grid-template-columns: minmax(320px, 460px) minmax(0, 1fr); gap: 18px; align-items: start; }
.span-2 { grid-column: 1 / -1; }
.quick-card { display: block; color: #111; text-decoration: none; min-height: 126px; }
.quick-card p { color: #666; margin-top: 10px; line-height: 1.6; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.panel-head span { color: #888; font-size: 13px; }
.stack-form { display: grid; gap: 10px; }
label { color: #555; font-size: 13px; }
input, select, textarea { width: 100%; border: 1px solid #d8d3c8; border-radius: 8px; background: #fff; padding: 10px 12px; transition: border-color .18s ease, box-shadow .18s ease, background-color .18s ease; }
input:focus, select:focus, textarea:focus { outline: none; border-color: #111; box-shadow: 0 0 0 3px rgba(17,17,17,.08); background: #fffefa; }
input, select { height: 38px; }
textarea { min-height: 150px; resize: vertical; }
.check { display: flex; align-items: center; gap: 8px; }
.check input { width: auto; height: auto; }
button { height: 36px; border: 0; border-radius: 8px; background: #050505; color: #fff; padding: 0 14px; cursor: pointer; font-weight: 700; white-space: nowrap; transition: transform .16s ease, box-shadow .16s ease, background-color .16s ease, border-color .16s ease; }
button:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(17,17,17,.14); }
button:active { transform: translateY(0); box-shadow: none; }
button.ghost { background: transparent; color: #555; border: 1px solid #ddd8ce; }
button.ghost:hover { color: #111; border-color: #bfb7a9; background: #fff; }
button.danger { background: #b91c1c; }
button.danger:hover { background: #991b1b; }
.primary.wide-btn { width: 100%; height: 42px; font-size: 16px; }
.inline-form { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center; }
.inline-form input, .inline-form select { width: auto; min-width: 130px; }
.table-wrap { overflow: auto; border: 1px solid #e5e1d8; border-radius: 8px; transition: border-color .18s ease, box-shadow .18s ease; }
.table-wrap:hover { border-color: #d2cabd; box-shadow: 0 10px 24px rgba(17,17,17,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px 12px; border-bottom: 1px solid #eeeae2; text-align: left; vertical-align: top; }
th { color: #666; background: #fbfaf7; font-weight: 700; white-space: nowrap; }
tbody tr { transition: background-color .16s ease; }
tbody tr:hover { background: #fbfaf7; }
code { font-family: Consolas, monospace; font-size: 12px; }
.chip { display: inline-block; border: 1px solid #d8d3c8; border-radius: 999px; padding: 2px 8px; background: #fbfaf7; transition: border-color .16s ease, background-color .16s ease; }
.empty { color: #888; text-align: center; padding: 24px; }
.long-text { min-width: 260px; white-space: pre-wrap; line-height: 1.5; }
.actions { display: flex; gap: 8px; }
.expiry-form { min-width: 250px; display: grid; gap: 7px; }
.expiry-row { display: grid; grid-template-columns: minmax(168px, 1fr) auto; gap: 8px; align-items: center; }
.expiry-row input { height: 34px; padding: 7px 10px; border-radius: 7px; font-weight: 700; }
.expiry-row button { height: 34px; min-width: 54px; padding: 0 12px; }
.expiry-current { color: #64748b; font-size: 12px; line-height: 1.45; }
.usage-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.usage-card { border: 1px solid #e5e1d8; border-radius: 8px; background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); padding: 14px; transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease; }
.usage-card:hover { transform: translateY(-2px); border-color: #bfdbfe; box-shadow: 0 12px 26px rgba(37, 99, 235, .11); }
.usage-card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.usage-card-head strong { font-size: 18px; }
.usage-card-head span { color: #64748b; font-size: 12px; font-weight: 700; }
.chart-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; margin-bottom: 12px; }
.chart-tab { height: 32px; border: 1px solid #dbeafe; border-radius: 8px; background: #eff6ff; color: #1e40af; padding: 0 8px; font-size: 12px; box-shadow: none; }
.chart-tab:hover, .chart-tab.is-active { background: #2563eb; border-color: #2563eb; color: #fff; box-shadow: 0 8px 16px rgba(37,99,235,.16); }
.usage-chart { min-height: 200px; position: relative; }
.chart-pane { display: none; min-height: 190px; animation: chartFade .2s ease-out both; }
.chart-pane.is-active { display: block; }
.chart-stage { position: relative; min-height: 190px; }
.line-svg, .radar-svg { width: 100%; height: 190px; display: block; overflow: visible; }
.line-svg text, .radar-svg text { fill: #64748b; font-size: 11px; font-weight: 700; }
.chart-axis, .radar-axis { stroke: #dbeafe; stroke-width: 1.4; }
.chart-line { fill: none; stroke: #2563eb; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 8px 10px rgba(37,99,235,.18)); }
.chart-point { position: absolute; left: var(--point-x); top: var(--point-y); width: 24px; height: 24px; border-radius: 999px; background: #fff; color: #1d4ed8; border: 2px solid #2563eb; padding: 0; transform: translate(-50%, -50%); box-shadow: 0 8px 18px rgba(37,99,235,.2); font-size: 10px; line-height: 20px; overflow: visible; }
.chart-point span { pointer-events: none; }
.chart-point:hover, .chart-point:focus, .chart-point.is-active { transform: translate(-50%, -50%) scale(1.08); box-shadow: 0 10px 22px rgba(37,99,235,.24); }
.chart-point::after, .chart-hotspot::after { content: attr(data-tooltip); position: absolute; left: 50%; bottom: calc(100% + 8px); transform: translate(-50%, 6px); opacity: 0; pointer-events: none; white-space: nowrap; border: 1px solid #bfdbfe; border-radius: 8px; background: #eff6ff; color: #1e3a8a; padding: 6px 8px; font-size: 12px; font-weight: 800; box-shadow: 0 10px 24px rgba(37,99,235,.16); transition: opacity .16s ease, transform .16s ease; z-index: 4; }
.chart-point:hover::after, .chart-point:focus::after, .chart-point.is-active::after, .chart-hotspot:hover::after, .chart-hotspot:focus::after, .chart-hotspot.is-active::after { opacity: 1; transform: translate(-50%, 0); }
.pie-layout { min-height: 190px; display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 14px; align-items: center; }
.pie-visual { width: 132px; height: 132px; border-radius: 50%; box-shadow: inset 0 0 0 14px rgba(255,255,255,.72), 0 12px 24px rgba(37,99,235,.12); }
.pie-legend { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
.pie-legend-item { position: relative; height: 30px; display: flex; align-items: center; justify-content: flex-start; gap: 6px; border: 1px solid #dbeafe; border-radius: 8px; background: #fff; color: #1f2937; padding: 0 8px; box-shadow: none; font-size: 12px; }
.pie-legend-item span { width: 9px; height: 9px; border-radius: 99px; flex: 0 0 auto; }
.pie-legend-item:hover, .pie-legend-item.is-active { transform: translateY(-1px); border-color: #93c5fd; background: #eff6ff; box-shadow: none; }
.radar-ring { fill: none; stroke: #dbeafe; stroke-width: 1.2; }
.radar-area { fill: rgba(37,99,235,.18); stroke: #2563eb; stroke-width: 3; filter: drop-shadow(0 8px 12px rgba(37,99,235,.14)); }
.bar-chart { min-height: 190px; display: grid; grid-template-columns: repeat(6, minmax(34px, 1fr)); gap: 9px; align-items: end; padding: 10px 4px 0; }
.usage-bar { position: relative; height: 158px; width: 100%; display: grid; grid-template-rows: 1fr auto auto; align-items: end; justify-items: center; border: 0; border-radius: 8px; background: transparent; color: #1f2937; padding: 0; box-shadow: none; overflow: visible; }
.usage-bar:hover, .usage-bar:focus, .usage-bar.is-active { transform: translateY(-2px); box-shadow: none; }
.usage-bar-fill { width: 100%; height: var(--bar-height); min-height: 6px; border-radius: 8px 8px 5px 5px; background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,.35), 0 8px 16px rgba(37,99,235,.16); transition: height .24s ease, filter .18s ease, transform .18s ease; }
.usage-bar:hover .usage-bar-fill, .usage-bar:focus .usage-bar-fill, .usage-bar.is-active .usage-bar-fill { filter: saturate(1.08); transform: scaleX(1.04); }
.usage-value { margin-top: 7px; font-size: 13px; font-weight: 800; }
.usage-label { margin-top: 3px; color: #64748b; font-size: 12px; }
.usage-bar::after { bottom: calc(var(--bar-height) + 54px); }
.settings-list { display: grid; gap: 10px; }
.settings-list div { display: flex; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid #eeeae2; padding-bottom: 10px; }
.settings-list span { color: #666; }
.settings-list strong { text-align: right; overflow-wrap: anywhere; }
.login-body { min-height: 100vh; display: grid; place-items: center; }
.login-panel { width: min(380px, calc(100vw - 32px)); border: 1px solid #ddd8ce; border-radius: 8px; background: #fff; padding: 28px; animation: consoleEnter .32s ease-out both; }
.brand-line { color: #777; font-size: 12px; font-weight: 800; margin-bottom: 14px; }
.login-panel form { display: grid; gap: 10px; margin-top: 18px; }
.error { color: #b91c1c; margin-top: 12px; }
@keyframes consoleEnter {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes chartFade {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
@media (max-width: 980px) {
  .sidebar { position: static; width: auto; border-right: 0; border-bottom: 1px solid #dedbd2; }
  .console { margin-left: 0; padding: 20px; }
  .page-head, .split, .grid, .metrics { grid-template-columns: 1fr; }
  .usage-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: auto; }
}
"""


_DASHBOARD_JS = """
document.addEventListener('DOMContentLoaded', () => {
  const activateHotspot = (target, selector) => {
    document.querySelectorAll(selector + '.is-active').forEach((item) => {
      if (item !== target) item.classList.remove('is-active');
    });
    target.classList.toggle('is-active');
  };

  document.querySelectorAll('.chart-tab').forEach((tab) => {
    const switchChart = () => {
      const card = tab.closest('.usage-card');
      if (!card) return;
      const type = tab.dataset.chartType;
      card.querySelectorAll('.chart-tab').forEach((item) => {
        item.classList.toggle('is-active', item === tab);
      });
      card.querySelectorAll('.chart-pane').forEach((pane) => {
        pane.classList.toggle('is-active', pane.dataset.chartType === type);
      });
    };
    tab.addEventListener('click', switchChart);
  });

  document.querySelectorAll('.usage-bar, .chart-point, .chart-hotspot').forEach((bar) => {
    const activate = () => {
      activateHotspot(bar, '.usage-bar, .chart-point, .chart-hotspot');
    };
    bar.addEventListener('touchstart', (event) => {
      event.preventDefault();
      activate();
    }, { passive: false });
    bar.addEventListener('click', activate);
  });
});
"""


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
