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
            f'<span>{label}</span><span class="mc-nav-arrow" aria-hidden="true">›</span></a>'
        )
    snapshot_time = datetime.now(timezone(timedelta(hours=8)))
    timestamp = snapshot_time.strftime("%Y-%m-%d %H:%M:%S")
    description = _DESCRIPTIONS.get(active, "管理服务配置与运行数据。")
    content = f'''
<a class="mc-skip-link" href="#main-content">跳转到主内容</a>
<aside class="mc-sidebar">
  <a class="mc-brand" href="/dashboard" aria-label="Miracle 控制台"><span class="mc-monogram" aria-hidden="true">M</span><span>Miracle<small>管理控制台</small></span></a>
  <button class="mc-nav-toggle ghost" type="button" aria-expanded="false" aria-controls="dashboard-navigation">导航菜单<span aria-hidden="true">＋</span></button>
  <nav id="dashboard-navigation" class="mc-navigation" aria-label="管理导航">{''.join(navigation)}</nav>
  <div class="mc-sidebar-footer"><span>Miracle Console</span><small>让每一次管理清晰有序</small></div>
</aside>
<div class="mc-workspace">
  <header class="mc-context-bar"><div class="mc-breadcrumb"><span>工作空间</span><span aria-hidden="true">/</span><strong>{escape(title)}</strong></div><form method="post" action="/dashboard/logout"><button class="ghost mc-logout" type="submit">退出登录</button></form></header>
  <main id="main-content" class="mc-main" tabindex="-1">
    {_preview_notice()}
    <div class="mc-page-heading"><div><p class="mc-eyebrow">MIRACLE / CONSOLE</p><h1>{escape(title)}</h1><p class="mc-page-description">{description}</p></div><div class="mc-snapshot"><span>数据快照 · 北京时间</span><time datetime="{snapshot_time.isoformat(timespec='seconds')}">{timestamp}</time></div></div>
    <div class="mc-content">{body}</div>
    <footer class="mc-page-footer"><span>Miracle 管理控制台</span><span>数据以当前页面快照为准</span></footer>
  </main>
</div>'''
    return _document(title, content)


def render_login(error: str = "") -> str:
    message = f'<div class="notice error" role="alert">{escape(error)}</div>' if error else ""
    content = f'''
<main class="mc-login-shell">
  <a class="mc-brand" href="/dashboard"><span class="mc-monogram" aria-hidden="true">M</span><span>Miracle<small>管理控制台</small></span></a>
  {_preview_notice()}
  <section class="mc-login-card" aria-labelledby="login-title">
    <p class="mc-eyebrow">WELCOME BACK</p><h1 id="login-title">登录控制台</h1>
    <p class="mc-page-description">使用管理令牌，进入你的工作空间。</p>
    {message}
    <form class="stack-form" method="post" action="/dashboard/login">
      <div><label for="admin-token">管理令牌</label><input id="admin-token" name="token" type="password" required autocomplete="current-password" placeholder="请输入管理令牌" aria-describedby="token-help"><p id="token-help" class="field-note">请输入服务配置中设置的管理令牌。</p></div>
      <button type="submit" class="wide-btn">登录控制台<span aria-hidden="true"> →</span></button>
    </form>
  </section><p class="mc-login-footer">Miracle Console · 管理工作，从这里开始</p>
</main>'''
    return _document("登录", content, login=True)
