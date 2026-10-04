"""Shared, dependency-free presentation for the server-rendered dashboard."""

from datetime import datetime, timedelta, timezone
from html import escape
import os
from pathlib import Path


_DIRECTORY = Path(__file__).resolve().parent
_NAVIGATION = (
    ("overview", "/dashboard", "控制台", "工作空间"),
    ("limits", "/dashboard/limits", "获取限制", "工作空间"),
    ("users", "/dashboard/users", "用户列表", "工作空间"),
    ("permissions", "/dashboard/permissions", "权限管理", "工作空间"),
    ("bans", "/dashboard/bans", "封禁名单", "工作空间"),
    ("ads", "/dashboard/ads", "广告管理", "运营与服务"),
    ("logs", "/dashboard/logs", "日志审计", "运营与服务"),
    ("ai", "/dashboard/ai", "AI 对话", "运营与服务"),
    ("image-ai", "/dashboard/image-ai", "AI 生图", "运营与服务"),
    ("settings", "/dashboard/settings", "系统设置", "系统"),
)
_DESCRIPTIONS = {
    "overview": "查看服务概况、资源使用情况与最近的管理动态。",
    "limits": "查看资源获取情况，管理每位用户的获取额度。",
    "users": "查看用户资料、使用记录与账户状态。",
    "permissions": "管理角色授权，让每位成员拥有合适的访问权限。",
    "bans": "查看和管理受限用户，保持服务有序运行。",
    "ads": "维护广告内容、投放状态与有效时间。",
    "logs": "追溯管理操作与服务事件，定位需要关注的问题。",
    "ai": "配置对话服务，测试模型响应与连接状态。",
    "image-ai": "配置图像生成服务，测试并查看生成结果。",
    "settings": "查看服务配置与运行环境。",
}

_ICONS = {
    "brand": '<path d="m13 2-8 12h6l-1 8 9-13h-6z"/>',
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "limits": '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5"/>',
    "permissions": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
    "bans": '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
    "ads": '<path d="m4 9 15-5v16L4 15zM4 9H2v6h2m2 1 2 5h4l-2-4"/>',
    "logs": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',
    "ai": '<path d="M21 11a8 8 0 0 1-8 8H7l-4 3v-8a8 8 0 0 1 8-8h2M18 2v6m-3-3h6"/><path d="M7 11h7m-7 4h4"/>',
    "image-ai": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
    "settings": '<path d="m10 3-.6 2.4-2 .9-2.2-.7-2 3.4 1.7 1.7v2.6L3.2 15l2 3.4 2.2-.7 2 .9.6 2.4h4l.6-2.4 2-.9 2.2.7 2-3.4-1.7-1.7v-2.6L20.8 9l-2-3.4-2.2.7-2-.9L14 3z"/><circle cx="12" cy="12" r="3"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-14 4h3"/>',
    "arrow": '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9"/>',
}


def icon(name: str) -> str:
    """Return a decorative line icon from the dashboard's small shared set."""
    content = _ICONS.get(name, _ICONS["overview"])
    return ('<svg class="mc-icon" viewBox="0 0 24 24" width="20" height="20" '
            'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true" focusable="false">{content}</svg>')


def _brand() -> str:
    return (f'<span class="mc-brand-emblem">{icon("brand")}</span>'
            '<span class="mc-brand-copy"><strong>Miracle</strong><small>管理终端</small></span>')


def _document(title: str, content: str, *, login: bool = False) -> str:
    css = (_DIRECTORY / "dashboard.css").read_text(encoding="utf-8")
    js = (_DIRECTORY / "dashboard.js").read_text(encoding="utf-8")
    return f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)} · Miracle</title>
<style>{css}</style></head>
<body class="{'mc-login-page' if login else 'mc-dashboard'}">{content}<script>{js}</script></body></html>'''


def _preview_notice() -> str:
    if os.environ.get("DASHBOARD_PREVIEW") == "1":
        return '<div class="mc-preview-banner" role="status"><strong>预览模式</strong><span>当前页面包含演示数据，仅用于界面预览。</span></div>'
    return ""


def render_layout(title: str, active: str, body: str) -> str:
    """Wrap trusted application-generated HTML in the dashboard shell."""
    navigation = []
    previous_group = None
    for key, href, label, group in _NAVIGATION:
        if group != previous_group:
            navigation.append(f'<div class="mc-nav-group">{group}</div>')
            previous_group = group
        selected = key == active
        current = ' aria-current="page"' if selected else ""
        navigation.append(
            f'<a class="mc-nav-link{" is-active" if selected else ""}" href="{href}"{current}>'
            f'{icon(key)}<span>{label}</span></a>'
        )
    snapshot_time = datetime.now(timezone(timedelta(hours=8)))
    timestamp = snapshot_time.strftime("%Y-%m-%d %H:%M:%S")
    description = _DESCRIPTIONS.get(active, "管理服务配置与运行数据。")
    content = f'''
<a class="mc-skip-link" href="#main-content">跳转到主内容</a>
<aside class="mc-sidebar">
  <a class="mc-brand" href="/dashboard" aria-label="Miracle 控制台">{_brand()}</a>
  <button class="mc-nav-toggle ghost" type="button" aria-expanded="false" aria-controls="dashboard-navigation">导航菜单<span aria-hidden="true">＋</span></button>
  <nav id="dashboard-navigation" class="mc-navigation" aria-label="管理导航">{''.join(navigation)}</nav>
  <div class="mc-admin"><span class="mc-admin-avatar" aria-hidden="true">M</span><div><strong>管理员</strong><small>管理工作空间</small></div></div>
</aside>
<div class="mc-workspace">
  <header class="mc-context-bar">
    <div class="mc-page-heading"><h1>{escape(title)}</h1><p class="mc-page-description">{description}</p></div>
    <div class="mc-context-actions"><div class="mc-snapshot"><span>快照 · 北京时间</span><time datetime="{snapshot_time.isoformat(timespec='seconds')}">{timestamp}</time></div><a class="mc-settings-link" href="/dashboard/settings" aria-label="系统设置">{icon("settings")}</a><form method="post" action="/dashboard/logout"><button class="ghost mc-logout" type="submit">退出登录</button></form></div>
  </header>
  <main id="main-content" class="mc-main" tabindex="-1">
    {_preview_notice()}
    <div class="mc-content">{body}</div>
  </main>
</div>'''
    return _document(title, content)


def render_login(error: str = "") -> str:
    message = f'<div class="notice error" role="alert">{escape(error)}</div>' if error else ""
    content = f'''
<main class="mc-login-shell">
  {_preview_notice()}
  <section class="mc-login-card" aria-labelledby="login-title">
    <h1 id="login-title" class="mc-brand">{_brand()}<span class="sr-only">管理员登录</span></h1>
    <p class="mc-page-description">输入管理令牌以进入后台控制台。</p>
    {message}
    <form class="stack-form" method="post" action="/dashboard/login">
      <div><label for="admin-token">管理令牌</label><input id="admin-token" name="token" type="password" required autocomplete="current-password" placeholder="请输入管理令牌" aria-describedby="token-help"></div>
      <button type="submit" class="wide-btn">登录</button>
    </form>
    <p id="token-help" class="mc-login-security">{icon("permissions")}<span>使用服务配置中的 <code>ADMIN_CONTROL_TOKEN</code>，请仅由管理员持有。</span></p>
  </section>
</main>'''
    return _document("登录", content, login=True)
