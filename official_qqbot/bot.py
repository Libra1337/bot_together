"""
QQ 官方 Bot 主程序 - 全功能版
基于 QQ 开放平台 API + WebSocket 协议
独立运行，与 NapCat Bot 互不干扰
"""

import os
import sys
import json
import asyncio
import logging
import re
import time as _time_mod
import yaml
import httpx
import websockets
from difflib import SequenceMatcher
from collections import OrderedDict

# 共享冷却
import shared_cooldown as _shared_cd

from handlers.ai_chat import AIChat
from handlers import nfa, sauth, bjd, hypban, web_crawler
from handlers import fun, bilibili, douyin, music, github
from handlers import email_sender
from feature_flags import FeatureFlags
from plugin_runtime import PluginRuntime

# ====== 版本 ======
BOT_VERSION = "1.1.0"
BOT_BUILD_DATE = "2026-04-13"
_start_time: float = _time_mod.time()

# ====== 日志 ======
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("OfficialBot")

# ====== 加载配置 ======
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_BOT_DIR, "config.yaml")
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

BOT_CONFIG = config.get("bot", {})
AI_CONFIG = config.get("ai", {})
EMAIL_CONFIG = config.get("email", {})
APP_ID = BOT_CONFIG["app_id"]
APP_SECRET = BOT_CONFIG["app_secret"]
SANDBOX = BOT_CONFIG.get("sandbox", False)
ADMIN_SECRET = config.get("admin_secret", "miracle2026")
API_BASE = (
    "https://sandbox.api.sgroup.qq.com" if SANDBOX else "https://api.sgroup.qq.com"
)
AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"

# ====== Admin/Staff/Ban 系统（openid） ======
ADMIN_FILE = os.path.join(_BOT_DIR, "data", "admins.json")
STAFF_FILE = os.path.join(_BOT_DIR, "data", "staff.json")
BAN_FILE = os.path.join(_BOT_DIR, "data", "banned.json")


def _load_json_set(filepath) -> set[str]:
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(str(x) for x in data)
    except Exception:
        pass
    return set()


def _save_json_set(filepath, data: set):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(list(data), f, ensure_ascii=False)
    except Exception as e:
        _log.warning(f"保存失败 {filepath}: {e}")


def _load_staff_dict() -> dict[str, dict]:
    try:
        if os.path.exists(STAFF_FILE):
            with open(STAFF_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_staff_dict():
    try:
        os.makedirs(os.path.dirname(STAFF_FILE), exist_ok=True)
        with open(STAFF_FILE, "w", encoding="utf-8") as f:
            json.dump(_staff, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning(f"保存 staff 失败: {e}")


_admin_set: set[str] = _load_json_set(ADMIN_FILE)
_staff: dict[str, dict] = _load_staff_dict()
_staff_logged_in: set[str] = set()
_banned_set: set[str] = _load_json_set(BAN_FILE)

_log.info(
    f"[Admin] 已加载 {len(_admin_set)} 个管理员, {len(_staff)} 个 Staff, {len(_banned_set)} 个封禁"
)


def _is_admin(user_openid: str) -> bool:
    return user_openid in _admin_set


def _is_admin_or_staff(user_openid: str) -> bool:
    return user_openid in _admin_set or user_openid in _staff_logged_in


def _is_banned(user_openid: str) -> bool:
    return user_openid in _banned_set


# ====== 邮箱绑定 {openid: email} ======
EMAIL_BIND_FILE = os.path.join(_BOT_DIR, "data", "email_binds.json")


def _load_email_binds() -> dict[str, str]:
    try:
        if os.path.exists(EMAIL_BIND_FILE):
            with open(EMAIL_BIND_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_email_binds():
    try:
        os.makedirs(os.path.dirname(EMAIL_BIND_FILE), exist_ok=True)
        with open(EMAIL_BIND_FILE, "w", encoding="utf-8") as f:
            json.dump(_email_binds, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning(f"[邮箱] 保存绑定失败: {e}")


_email_binds: dict[str, str] = _load_email_binds()
_log.info(f"[邮箱] 已加载 {len(_email_binds)} 个邮箱绑定")

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


async def _send_result_email(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    """通过配置的 SMTP 发送邮件"""
    return await email_sender.send_email(
        smtp_host=EMAIL_CONFIG.get("smtp_host", ""),
        smtp_port=EMAIL_CONFIG.get("smtp_port", 465),
        smtp_user=EMAIL_CONFIG.get("smtp_user", ""),
        smtp_pass=EMAIL_CONFIG.get("smtp_pass", ""),
        from_addr=EMAIL_CONFIG.get("from_addr", ""),
        to_addr=to_addr,
        subject=subject,
        body=body,
        use_tls=EMAIL_CONFIG.get("use_tls", True),
        from_name=EMAIL_CONFIG.get("from_name", "Miracle Team"),
    )


def _normalize_email_addr(email: str) -> str:
    return (email or "").strip()


def _is_valid_email_addr(email: str) -> bool:
    return bool(_EMAIL_RE.match(_normalize_email_addr(email)))


def _get_bound_email(user_id: str) -> str:
    return _email_binds.get(user_id, "").strip()


def _mask_email_addr(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = f"{local[:2]}***{local[-1]}"
    return f"{masked_local}@{domain}"


async def _require_bound_email(ctx, user_id: str) -> bool:
    if _get_bound_email(user_id):
        return True
    await reply(
        ctx,
        "请先绑定邮箱再领取资源喵~\n输入：/bind 你的邮箱\n例如：/bind 123456@qq.com",
    )
    return False


async def _send_resource_result(
    ctx,
    user_id: str,
    resource_key: str,
    resource_label: str,
    subject: str,
    result: str,
) -> bool:
    to_addr = _get_bound_email(user_id)
    ok, err = await _send_result_email(to_addr, subject, result)
    masked_addr = _mask_email_addr(to_addr)
    if ok:
        await reply(ctx, f"{resource_label} 已发送到邮箱 {masked_addr}，请查收喵~")
        return True

    _log.warning(f"[{resource_key}] 邮件发送失败 -> {masked_addr}: {err}")
    await reply(ctx, f"{resource_label} 邮件发送失败，已改为当前会话发送喵~\n{result}")
    return False


# ====== AI ======
system_prompt = ""
prompt_file = AI_CONFIG.get("system_prompt_file", "")
if prompt_file:
    prompt_path = os.path.join(_BOT_DIR, prompt_file)
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()
        _log.info(f"已加载系统提示词（{len(system_prompt)} 字）")

ai_chat = AIChat(
    base_url=AI_CONFIG.get("base_url", ""),
    api_key=AI_CONFIG.get("api_key", ""),
    model=AI_CONFIG.get("model", ""),
    system_prompt=system_prompt,
    max_history=AI_CONFIG.get("max_history", 10),
)

# ====== 插件运行时 ======
feature_flags = FeatureFlags(os.path.join(_BOT_DIR, "data", "plugins.json"))
plugin_runtime = PluginRuntime(
    plugins_dir=os.path.join(_BOT_DIR, "plugins"),
    state_file=os.path.join(_BOT_DIR, "data", "plugins.json"),
    reply_func=reply if "reply" in globals() else None,
)


def _feature_enabled(feature_id: str) -> bool:
    return feature_flags.enabled(feature_id)


async def _reply_feature_disabled(ctx, label: str) -> bool:
    await reply(ctx, f"{label} 功能已在面板停用喵~")
    return True


def _disabled_builtin_for_command(lower: str, content: str) -> tuple[str, str] | None:
    bind_like = lower in (
        "/bind",
        "bind",
        "绑定邮箱",
        "/绑定邮箱",
        "绑邮箱",
        "/unbind",
        "unbind",
        "解绑邮箱",
        "/解绑邮箱",
        "取消邮箱",
    ) or bool(re.match(r"^(?:/bind|绑定邮箱|/绑定邮箱)\s+", content, re.IGNORECASE))
    checks = [
        (
            "builtin.admin",
            "Bot 管理指令",
            lower in ("/auth", "auth", "/quit", "quit", "/admin", "admin")
            or content.startswith(("/auth ", "auth ", "/ban ", "/unban ", "/addstaff ", "/deletestaff "))
            or bool(re.match(r"^/ad(s?\+|s?-|)\s*(.*)", content or "", re.DOTALL)),
        ),
        ("builtin.stock", "库存/邮箱", bind_like or lower in ("163", "/163", "stock", "/stock")),
        ("builtin.fun", "日常娱乐", lower in ("签到", "打卡", "运势", "今日运势", "抽签", "每日运势", "今日人品", "人品", "jrrp", "排行榜", "积分榜", "签到排行")),
        ("builtin.ai_chat", "AI 对话", lower in ("清除记忆", "重置记忆", "清空记忆", "重置对话", "清空对话")),
        ("builtin.nfa", "NFA", lower in ("nfa", "/nfa")),
        ("builtin.sauth", "4399 Sauth", lower in ("4399", "/4399")),
        ("builtin.bjd", "布吉岛查询", lower in ("bjd", "/bjd", "布吉岛")),
        ("builtin.hypban", "Hypixel 封禁", lower in ("hypban", "/hypban")),
        ("builtin.music", "点歌", bool(re.match(r"^(点歌|听歌|来首歌)(\s+.*)?$", content))),
        ("builtin.github", "GitHub 搜索", bool(re.match(r"^(搜索github|github搜|搜索gh)\s+(.+)", content, re.IGNORECASE))),
    ]
    for feature_id, label, matched in checks:
        if matched and not _feature_enabled(feature_id):
            return feature_id, label
    return None

# ====== 冷却/频率常量 ======
NFA_COOLDOWN = 1800
_NFA_HOUR_LIMIT = 5
_NFA_BAN_DURATION = 86400
_163_HOUR_LIMIT = 5
_163_BAN_DURATION = 86400

# ====== 交互状态 ======
# 点歌等待 {user_openid: {"ts": timestamp, "ctx": ctx}}
_music_waiting: dict[str, dict] = {}
# 点歌选择 {user_openid: {"songs": [...], "ctx": ctx, "ts": timestamp}}
_music_select: dict[str, dict] = {}
# GitHub 选择 {user_openid: {"repos": [...], "ctx": ctx, "ts": timestamp}}
_github_select: dict[str, dict] = {}
# 模糊指令确认 {user_openid: {"command": str, "ctx": ctx, "expire": timestamp}}
_fuzzy_waiting: dict[str, dict] = {}
# /ad 查看状态 {user_openid: expire_timestamp}
_ad_waiting: dict[str, float] = {}

# ====== 模糊指令 ======
_KNOWN_COMMANDS = {
    "签到",
    "打卡",
    "运势",
    "抽签",
    "今日运势",
    "每日运势",
    "今日人品",
    "人品",
    "jrrp",
    "帮助",
    "help",
    "菜单",
    "清除记忆",
    "重置记忆",
    "清空记忆",
    "重置对话",
    "清空对话",
    "nfa",
    "4399",
    "163",
    "stock",
    "bind",
    "绑定邮箱",
    "解绑邮箱",
    "bjd",
    "布吉岛",
    "hypban",
    "status",
    "datalog",
    "更新日志",
    "排行榜",
    "积分榜",
    "签到排行",
    "点歌",
    "听歌",
    "来首歌",
    "/nfa",
    "/4399",
    "/163",
    "/stock",
    "/bind",
    "/unbind",
    "/绑定邮箱",
    "/解绑邮箱",
    "/bjd",
    "/hypban",
    "/status",
    "/datalog",
    "/jrrp",
    "/ad",
}
_FUZZY_SPECS = [
    ("nfa", "获取 NFA Token"),
    ("4399", "获取 4399 Sauth"),
    ("163", "领取 163 小号"),
    ("stock", "查看全部库存"),
    ("/bind", "绑定资源接收邮箱"),
    ("bjd", "查询布吉岛版本"),
    ("hypban", "查询 Hypixel 封禁"),
    ("status", "查看运行状态"),
    ("datalog", "查看更新日志"),
    ("签到", "每日签到"),
    ("运势", "查看今日运势"),
    ("今日人品", "查看人品值"),
    ("帮助", "查看功能列表"),
    ("清除记忆", "重置 AI 对话"),
    ("排行榜", "查看签到排名"),
    ("点歌", "搜索歌曲"),
    ("/ad", "广告管理"),
]


def _find_fuzzy(content):
    best, best_score = None, 0
    for cmd, desc in _FUZZY_SPECS:
        score = SequenceMatcher(None, content.lower(), cmd.lower()).ratio()
        if score > best_score:
            best_score = score
            best = (cmd, desc)
    if best_score >= 0.55 and best:
        return best
    return None


# ====== 广告系统 ======
ADS_FILE = os.path.join(_BOT_DIR, "data", "ads.json")


def _load_ads():
    try:
        if os.path.exists(ADS_FILE):
            with open(ADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("content")]
    except Exception:
        pass
    return [
        {
            "id": 1,
            "content": "欢迎进入无限免费小号群喵：1097445697",
            "enabled": True,
            "active_until": None,
        }
    ]


def _save_ads():
    try:
        os.makedirs(os.path.dirname(ADS_FILE), exist_ok=True)
        with open(ADS_FILE, "w", encoding="utf-8") as f:
            json.dump(_ads, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_ads = _load_ads()
if not os.path.exists(ADS_FILE):
    _save_ads()


def _get_active_ads():
    now = _time_mod.time()
    result = []
    for ad in _ads:
        if not ad.get("enabled"):
            continue
        until = ad.get("active_until")
        if isinstance(until, (int, float)) and until <= now:
            ad["enabled"] = False
            continue
        result.append(ad.get("content", ""))
    return result


def _append_ads(text):
    ads = _get_active_ads()
    if not ads:
        return text
    return f"{text}\n\n━━━ 广告 ━━━\n" + "\n".join(ads)


# ====== 签到系统（openid） ======
SIGN_FILE = os.path.join(_BOT_DIR, "data", "sign_official.json")


def _load_sign():
    try:
        if os.path.exists(SIGN_FILE):
            with open(SIGN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_sign(data):
    try:
        os.makedirs(os.path.dirname(SIGN_FILE), exist_ok=True)
        with open(SIGN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_sign_data = _load_sign()


def do_sign_in(user_openid):
    import datetime

    today = datetime.date.today().isoformat()
    user = _sign_data.get(user_openid, {"points": 0, "streak": 0, "last": ""})
    if user.get("last") == today:
        return f"你今天已经签到过了喵~\n当前积分：{user['points']}\n连签：{user['streak']}天"

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    if user.get("last") == yesterday:
        user["streak"] = user.get("streak", 0) + 1
    else:
        user["streak"] = 1

    bonus = min(user["streak"], 7)
    points = 10 + bonus
    user["points"] = user.get("points", 0) + points
    user["last"] = today
    _sign_data[user_openid] = user
    _save_sign(_sign_data)
    return (
        f"签到成功喵~\n"
        f"获得 {points} 积分（含连签加成 +{bonus}）\n"
        f"当前积分：{user['points']}\n"
        f"连续签到：{user['streak']}天"
    )


# ====== Access Token ======
_access_token: str = ""
_token_expire_at: float = 0


async def refresh_access_token():
    global _access_token, _token_expire_at
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            AUTH_URL, json={"appId": APP_ID, "clientSecret": APP_SECRET}
        )
        data = resp.json()
        _access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        _token_expire_at = _time_mod.time() + expires_in - 60
        _log.info(f"[Auth] access_token 有效期 {expires_in}s")


async def get_auth_header():
    if _time_mod.time() >= _token_expire_at:
        await refresh_access_token()
    return {
        "Authorization": f"QQBot {_access_token}",
        "Content-Type": "application/json",
    }


async def get_gateway_auth_header():
    if _time_mod.time() >= _token_expire_at:
        await refresh_access_token()
    return {
        "Authorization": f"Bearer {_access_token}",
        "Content-Type": "application/json",
    }


# ====== 消息发送 ======
_msg_seq_counter: dict[str, int] = {}


# QQ 官方 API 禁止消息包含 URL 域名，需要脱敏
_URL_SANITIZE_DOMAINS = [
    ".com",
    ".cn",
    ".net",
    ".org",
    ".io",
    ".me",
    ".de",
    ".tv",
    ".cc",
    ".top",
    ".xyz",
    ".app",
    ".dev",
    ".lol",
    ".site",
    ".online",
    "http://",
    "https://",
    "www.",
]


def _sanitize_url(text: str) -> str:
    """把消息中的域名/URL脱敏，避免 QQ 官方 API 400 拒绝"""
    result = text
    for domain in _URL_SANITIZE_DOMAINS:
        if domain in result:
            safe = domain.replace(".", "。").replace("://", "ˊ//")
            result = result.replace(domain, safe)
    return result


async def send_group_msg(group_openid, content, msg_id):
    content = _sanitize_url(_append_ads(content))
    if len(content) > 2000:
        content = content[:2000] + "\n...(内容过长已截断)"
    headers = await get_auth_header()
    key = f"g_{group_openid}_{msg_id}"
    _msg_seq_counter[key] = _msg_seq_counter.get(key, 0) + 1
    body = {
        "content": content,
        "msg_type": 0,
        "msg_id": msg_id,
        "msg_seq": _msg_seq_counter[key],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API_BASE}/v2/groups/{group_openid}/messages",
                headers=headers,
                json=body,
            )
            if resp.status_code not in (200, 201, 202, 204):
                _log.warning(f"[发送] 群消息失败 {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        _log.error(f"[发送] 群消息异常: {e}")


async def send_c2c_msg(user_openid, content, msg_id):
    content = _sanitize_url(_append_ads(content))
    if len(content) > 2000:
        content = content[:2000] + "\n...(内容过长已截断)"
    headers = await get_auth_header()
    key = f"c_{user_openid}_{msg_id}"
    _msg_seq_counter[key] = _msg_seq_counter.get(key, 0) + 1
    body = {
        "content": content,
        "msg_type": 0,
        "msg_id": msg_id,
        "msg_seq": _msg_seq_counter[key],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API_BASE}/v2/users/{user_openid}/messages",
                headers=headers,
                json=body,
            )
            if resp.status_code not in (200, 201, 202, 204):
                _log.warning(f"[发送] 私聊失败 {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        _log.error(f"[发送] 私聊异常: {e}")


# ====== 统一回复 ======
async def reply(ctx, text):
    if ctx["type"] == "group":
        await send_group_msg(ctx["group_openid"], text, ctx["msg_id"])
    else:
        await send_c2c_msg(ctx["user_openid"], text, ctx["msg_id"])


async def reply_plain(ctx, text):
    """不带广告的回复"""
    text = _sanitize_url(text)
    if len(text) > 2000:
        text = text[:2000] + "\n...(内容过长已截断)"
    headers = await get_auth_header()

    if ctx["type"] == "group":
        url = f"{API_BASE}/v2/groups/{ctx['group_openid']}/messages"
        key = f"g_{ctx['group_openid']}_{ctx['msg_id']}"
    else:
        url = f"{API_BASE}/v2/users/{ctx['user_openid']}/messages"
        key = f"c_{ctx['user_openid']}_{ctx['msg_id']}"

    _msg_seq_counter[key] = _msg_seq_counter.get(key, 0) + 1
    body = {
        "content": text,
        "msg_type": 0,
        "msg_id": ctx["msg_id"],
        "msg_seq": _msg_seq_counter[key],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code not in (200, 201, 202, 204):
                _log.warning(f"[发送plain] {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        _log.error(f"[发送plain] 异常: {e}")


plugin_runtime.reply_func = reply


# ====== 指令处理 ======
async def handle_command(ctx, content):
    """处理所有指令，返回 True 表示已处理"""
    lower = content.lower().strip()
    user_id = ctx["user_openid"]

    # 帮助
    if lower in ("/help", "help", "帮助", "菜单"):
        await reply(
            ctx,
            (
                "Ciallo 曦曦官方Bot 指令列表喵~\n"
                "━━━ 日常功能 ━━━\n"
                "签到 / 打卡 — 每日签到得积分\n"
                "排行榜 — 查看签到排名\n"
                "运势 / 抽签 — 查看今日运势\n"
                "今日人品 — 每日人品值\n"
                "XX天气 — 查询天气（如：北京天气）\n"
                "━━━ 点歌/搜索 ━━━\n"
                "点歌 歌名 — 搜索歌曲\n"
                "点歌 — 进入点歌模式，再输歌名\n"
                "搜索GitHub 关键词 — 搜索仓库\n"
                "━━━ 小号/资源 ━━━\n"
                "nfa — 获取 NFA Token\n"
                "4399 — 获取 4399 Sauth\n"
                "163 — 领取 163 小号\n"
                "stock — 查看全部库存\n"
                "/bind 邮箱 — 绑定资源接收邮箱（领取前必需）\n"
                "/unbind — 取消邮箱绑定\n"
                "━━━ 查询功能 ━━━\n"
                "bjd — 查询布吉岛版本\n"
                "hypban — Hypixel 封禁统计\n"
                "status — 运行状态\n"
                "datalog — 完整更新日志\n"
                "/whois — 查看自己的 openid\n"
                "━━━ AI 对话 ━━━\n"
                "@我 + 任意内容 — AI 聊天\n"
                "清除记忆 — 重置对话上下文\n"
                "发送链接 — 自动网页分析\n"
                "发送B站/抖音链接 — 自动解析\n"
                "输错指令 — 智能纠正，回复 y 执行\n"
                "━━━ 管理指令（私聊） ━━━\n"
                "/auth 验证码 — 验证管理员身份\n"
                "/quit — 退出登陆\n"
                "/admin — 管理面板\n"
                "/ban openid — 封禁用户\n"
                "/unban openid — 解封用户\n"
                "/addstaff openid — 添加 Staff\n"
                "/deletestaff openid — 移除 Staff\n"
                "/ad — 广告管理\n"
                "/ad+ 内容 — 新增广告到列表\n"
                "/ad- 编号 — 删除广告\n"
                "/ads+ 编号 [时间] — 开启展示\n"
                "/ads- 编号 — 移除展示\n"
                "━━━━━━━━━━━━━━\n"
                f"v{BOT_VERSION} | 构建：{BOT_BUILD_DATE}\n"
                "群聊 @我 或私聊直接发消息即可喵~"
            ),
        )
        return True

    disabled = _disabled_builtin_for_command(lower, content)
    if disabled:
        return await _reply_feature_disabled(ctx, disabled[1])

    # ===== 封禁检测 =====
    if _is_banned(user_id):
        await reply_plain(ctx, "您已被封禁，无法使用 Bot 喵~")
        return True

    # ===== /auth 验证 =====
    if lower == "/auth" or lower == "auth":
        if ctx["type"] != "c2c":
            await reply(ctx, "请私聊我发送 /auth 验证码 来验证身份喵~")
        else:
            await reply(ctx, "请发送：/auth 验证码\n例如：/auth miracle2026")
        return True

    if content.startswith("/auth ") or content.startswith("auth "):
        code = content.split(None, 1)[1].strip() if " " in content else ""
        if ctx["type"] != "c2c":
            await reply(ctx, "请私聊我验证喵~不要在群里发验证码！")
            return True

        # admin 验证
        if code == ADMIN_SECRET:
            _admin_set.add(user_id)
            _save_json_set(ADMIN_FILE, _admin_set)
            await reply_plain(
                ctx, "验证成功喵~您已成为管理员！\n授权已持久化，重启后无需重新验证~"
            )
            _log.info(f"[Auth] {user_id[:8]}... 成为 admin")
            return True

        # staff 密码验证
        if user_id in _staff:
            staff_info = _staff[user_id]
            if not staff_info.get("password"):
                staff_info["password"] = code
                _save_staff_dict()
                _staff_logged_in.add(user_id)
                await reply_plain(
                    ctx, f"Staff 密码设置成功喵~已登陆！\n（密码：{code}）"
                )
                _log.info(f"[Staff] {user_id[:8]}... 激活")
                return True
            if staff_info.get("password") == code:
                _staff_logged_in.add(user_id)
                await reply_plain(ctx, "Staff 登陆成功喵~")
                _log.info(f"[Staff] {user_id[:8]}... 登陆")
                return True

        await reply_plain(ctx, "验证码不正确喵~")
        return True

    # ===== /quit =====
    if lower in ("/quit", "quit"):
        removed = False
        if user_id in _admin_set:
            _admin_set.discard(user_id)
            _save_json_set(ADMIN_FILE, _admin_set)
            removed = True
        if user_id in _staff_logged_in:
            _staff_logged_in.discard(user_id)
            removed = True
        await reply_plain(ctx, "已退出登陆喵~" if removed else "您当前没有登陆状态喵~")
        return True

    # ===== /admin 面板 =====
    if lower in ("/admin", "admin"):
        if not _is_admin(user_id):
            await reply(ctx, "需要管理权限喵~请先私聊 /auth 验证码")
            return True
        admin_count = len(_admin_set)
        staff_count = len(_staff)
        ban_count = len(_banned_set)
        lines = [
            f"曦曦官方Bot 管理面板",
            f"━━━━━━━━━━━━━━",
            f"管理员：{admin_count} 人",
            f"Staff：{staff_count} 人（在线 {len(_staff_logged_in)}）",
            f"封禁：{ban_count} 人",
            f"━━━━━━━━━━━━━━",
            f"可用指令：",
            f"  /ban openid — 封禁用户",
            f"  /unban openid — 解封用户",
            f"  /addstaff openid — 添加 Staff",
            f"  /deletestaff openid — 移除 Staff",
            f"  /ad — 广告管理",
        ]
        await reply_plain(ctx, "\n".join(lines))
        return True

    # ===== /ban =====
    if content.startswith("/ban "):
        if not _is_admin_or_staff(user_id):
            await reply(ctx, "需要管理权限喵~")
            return True
        target = content[5:].strip()
        if not target:
            await reply(ctx, "用法：/ban openid")
            return True
        _banned_set.add(target)
        _save_json_set(BAN_FILE, _banned_set)
        await reply_plain(ctx, f"已封禁 {target[:12]}... 喵~")
        _log.info(f"[Ban] {user_id[:8]}... 封禁了 {target[:12]}...")
        return True

    # ===== /unban =====
    if content.startswith("/unban "):
        if not _is_admin_or_staff(user_id):
            await reply(ctx, "需要管理权限喵~")
            return True
        target = content[7:].strip()
        if target not in _banned_set:
            await reply(ctx, "该用户不在封禁列表中喵~")
            return True
        _banned_set.discard(target)
        _save_json_set(BAN_FILE, _banned_set)
        await reply_plain(ctx, f"已解封 {target[:12]}... 喵~")
        _log.info(f"[Unban] {user_id[:8]}... 解封了 {target[:12]}...")
        return True

    # ===== /addstaff =====
    if content.startswith("/addstaff "):
        if not _is_admin(user_id):
            await reply(ctx, "仅 Admin 可添加 Staff 喵~")
            return True
        target = content[10:].strip()
        if not target:
            await reply(ctx, "用法：/addstaff openid")
            return True
        if target in _staff:
            await reply(ctx, "该用户已是 Staff 喵~")
            return True
        _staff[target] = {"password": "", "added_by": user_id[:12]}
        _save_staff_dict()
        await reply_plain(
            ctx, f"已添加 Staff {target[:12]}... 喵~\n对方需私聊 /auth 密码 激活"
        )
        _log.info(f"[Staff] {user_id[:8]}... 添加了 {target[:12]}...")
        return True

    # ===== /deletestaff =====
    if content.startswith("/deletestaff "):
        if not _is_admin(user_id):
            await reply(ctx, "仅 Admin 可移除 Staff 喵~")
            return True
        target = content[13:].strip()
        if target not in _staff:
            await reply(ctx, "该用户不是 Staff 喵~")
            return True
        del _staff[target]
        _staff_logged_in.discard(target)
        _save_staff_dict()
        await reply_plain(ctx, f"已移除 Staff {target[:12]}... 喵~")
        _log.info(f"[Staff] {user_id[:8]}... 移除了 {target[:12]}...")
        return True

    # ===== /whois 查看用户 openid =====
    if lower in ("/whois", "whois"):
        email = _email_binds.get(user_id, "未绑定")
        await reply_plain(ctx, f"你的 openid：\n{user_id}\n绑定邮箱：{email}")
        return True

    # ===== 绑定邮箱 =====
    bind_match = re.match(r"^(?:/bind|绑定邮箱|/绑定邮箱)\s+(\S+@\S+\.\S+)$", content, re.IGNORECASE)
    if bind_match:
        email = _normalize_email_addr(bind_match.group(1))
        if not _is_valid_email_addr(email):
            await reply(
                ctx,
                "邮箱格式不对喵~请输入：/bind 你的邮箱地址\n例如：/bind 123456@qq.com",
            )
            return True
        _email_binds[user_id] = email
        _save_email_binds()
        await reply_plain(
            ctx, f"邮箱绑定成功喵~\n{email}\n之后领取 nfa/4399/163 会自动发到这个邮箱！"
        )
        _log.info(f"[邮箱] {user_id[:8]}... 绑定 {email}")
        return True

    if lower in ("/bind", "bind", "绑定邮箱", "/绑定邮箱", "绑邮箱") or re.match(
        r"^(?:/bind|绑定邮箱|/绑定邮箱)\s+", content, re.IGNORECASE
    ):
        await reply(
            ctx,
            "请输入：/bind 你的邮箱地址\n例如：/bind 123456@qq.com\n绑定后才能领取 nfa/4399/163 喵~",
        )
        return True

    # ===== 解绑邮箱 =====
    if lower in ("/unbind", "unbind", "解绑邮箱", "/解绑邮箱", "取消邮箱"):
        if user_id in _email_binds:
            del _email_binds[user_id]
            _save_email_binds()
            await reply_plain(ctx, "已解绑邮箱喵~之后需要重新绑定邮箱才能领取资源。")
        else:
            await reply(ctx, "你还没有绑定邮箱喵~")
        return True

    # 签到
    if lower in ("签到", "打卡"):
        result = do_sign_in(user_id)
        await reply(ctx, result)
        return True

    # 运势
    if lower in ("运势", "今日运势", "抽签", "每日运势"):
        result = fun.get_fortune()
        await reply(ctx, result)
        return True

    # 今日人品
    if lower in ("今日人品", "人品", "jrrp"):
        result = fun.get_jrrp(user_id)
        await reply(ctx, result)
        return True

    # 清除记忆
    if lower in ("清除记忆", "重置记忆", "清空记忆", "重置对话", "清空对话"):
        chat_id = f"{ctx['type']}_{user_id}"
        ai_chat.clear_history(chat_id)
        await reply(ctx, "记忆已清除喵~我们重新开始吧！")
        return True

    # NFA
    if lower in ("nfa", "/nfa"):
        if not await _require_bound_email(ctx, user_id):
            return True

        banned, bh, bm = _shared_cd.is_banned("nfa", user_id)
        if banned:
            await reply(
                ctx, f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~"
            )
            return True
        in_cd, remain = _shared_cd.check_cooldown("nfa", user_id, NFA_COOLDOWN)
        if in_cd:
            await reply(
                ctx, f"获取太频繁啦喵~请 {remain // 60}分{remain % 60}秒 后再试~"
            )
            return True
        over, count = _shared_cd.check_hour_limit(
            "nfa", user_id, _NFA_HOUR_LIMIT, _NFA_BAN_DURATION
        )
        if over:
            await reply(
                ctx, f"一小时内频繁获取NFA（{count}次），疑似偷卡，已封禁24小时喵~"
            )
            return True
        _shared_cd.record_usage("nfa", user_id)
        result = await nfa.get_nfa_token("admin", "zutomayo0.")
        if "主人您的nfa来了喵" in result:
            result += "\n爱来自Miracle nfa bot喵~"
            await _send_resource_result(
                ctx, user_id, "NFA", "NFA", "Miracle NFA Token", result
            )
        else:
            await reply(ctx, result)
        _log.info(f"[NFA] {user_id[:8]}...")
        return True

    # 4399
    if lower in ("4399", "/4399"):
        if not await _require_bound_email(ctx, user_id):
            return True

        success, result = await sauth.get_sauth()
        if success:
            result += "\n爱来自Miracle小号网站喵~"
            await _send_resource_result(
                ctx, user_id, "4399", "4399 Sauth", "Miracle 4399 Sauth", result
            )
        else:
            await reply(ctx, result)
        _log.info(f"[4399] {user_id[:8]}...")
        return True

    # 163
    if lower in ("163", "/163"):
        if not await _require_bound_email(ctx, user_id):
            return True

        banned, bh, bm = _shared_cd.is_banned("163", user_id)
        if banned:
            await reply(
                ctx, f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~"
            )
            return True
        in_cd, remain = _shared_cd.check_cooldown("163", user_id, 60)
        if in_cd:
            await reply(ctx, f"一分钟内已获取过啦，请{remain}秒后再试喵~")
            return True
        over, count = _shared_cd.check_hour_limit(
            "163", user_id, _163_HOUR_LIMIT, _163_BAN_DURATION
        )
        if over:
            await reply(
                ctx, f"一小时内频繁获取（{count}次），疑似偷卡，已封禁24小时喵~"
            )
            return True
        _shared_cd.record_usage("163", user_id)

        accounts_file = os.path.join(_BOT_DIR, "data", "163accounts.txt")
        try:
            with open(accounts_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            valid = [
                l
                for l in lines
                if l.strip() and not l.strip().startswith("#") and "----" in l
            ]
            other = [l for l in lines if l not in valid]
            if not valid:
                await reply(ctx, "163小号暂时没有库存了喵~")
                return True
            parts = valid[0].strip().split("----", 1)
            account, password = (
                parts[0].strip(),
                (parts[1].strip() if len(parts) > 1 else "未知"),
            )
            with open(accounts_file, "w", encoding="utf-8") as f:
                f.writelines(other + valid[1:])
            result_163 = (
                f"主人您的163小号来了喵~\n"
                f"━━━━━━━━━━━━━━\n"
                f"账号：{account}\n"
                f"密码：{password}\n"
                f"━━━━━━━━━━━━━━\n"
                f"可能需要手机验证，需要主人自己过验证哦~\n"
                f"爱来自Miracle小号网~"
            )
            await _send_resource_result(
                ctx, user_id, "163", "163 小号", "Miracle 163 小号", result_163
            )
        except FileNotFoundError:
            await reply(ctx, "163小号文件不存在喵~")
        except Exception as e:
            _log.error(f"[163] {e}")
            await reply(ctx, "163获取出错了喵~")
        return True

    # stock
    if lower in ("stock", "/stock"):
        lines = ["Miracle Bot 库存总览喵~", "━━━━━━━━━━━━━━"]
        try:
            ok, count, _ = await nfa.get_nfa_stock()
            lines.append(f"NFA：{count}" if ok else "NFA：unavailable")
        except Exception:
            lines.append("NFA：unavailable")
        try:
            ok4, avail, total, _ = await sauth.get_4399_stock()
            lines.append(f"4399：{avail}/{total}" if ok4 else "4399：unavailable")
        except Exception:
            lines.append("4399：unavailable")
        try:
            af = os.path.join(_BOT_DIR, "data", "163accounts.txt")
            with open(af, "r", encoding="utf-8") as f:
                c163 = sum(
                    1
                    for l in f
                    if l.strip() and not l.strip().startswith("#") and "----" in l
                )
            lines.append(f"163：{c163}")
        except Exception:
            lines.append("163：unavailable")
        lines.append("━━━━━━━━━━━━━━")
        await reply(ctx, "\n".join(lines))
        return True

    # BJD
    if lower in ("bjd", "/bjd", "布吉岛"):
        info = await bjd.get_latest_version()
        await reply(
            ctx,
            bjd.build_update_msg(info, is_update=False)
            if info
            else "获取布吉岛版本失败喵~",
        )
        return True

    # Hypban
    if lower in ("hypban", "/hypban"):
        result = await hypban.get_ban_stats()
        await reply(ctx, result)
        return True

    # Status
    if lower in ("status", "/status"):
        uptime = int(_time_mod.time() - _start_time)
        h, m, s = uptime // 3600, uptime % 3600 // 60, uptime % 60
        await reply(
            ctx,
            (
                f"曦曦官方Bot 运行状态\n"
                f"━━━━━━━━━━━━━━\n"
                f"版本：v{BOT_VERSION}\n"
                f"运行时间：{h}小时{m}分{s}秒\n"
                f"AI 模型：{AI_CONFIG.get('model', '?')}\n"
                f"环境：{'沙箱' if SANDBOX else '正式'}\n"
                f"构建日期：{BOT_BUILD_DATE}"
            ),
        )
        return True

    # Datalog
    if lower in ("datalog", "/datalog", "更新日志"):
        await reply_plain(
            ctx,
            (
                f"曦曦官方Bot 更新日志\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"v{BOT_VERSION} ({BOT_BUILD_DATE})\n"
                f"· 官方 Bot 上线，基于 QQ 开放平台 API\n"
                f"· AI 对话 + 签到/运势/人品/天气\n"
                f"· NFA/4399/163/库存查询\n"
                f"· 布吉岛/Hypban 查询\n"
                f"· B站/抖音/网页链接解析\n"
                f"· 点歌/GitHub 搜索\n"
                f"· 广告系统/模糊指令/排行榜\n"
                f"· 跨 Bot 共享冷却防偷卡\n"
                f"━━━━━━━━━━━━━━━━━"
            ),
        )
        return True

    # 排行榜
    if lower in ("排行榜", "积分榜", "签到排行"):
        if not _sign_data:
            await reply(ctx, "还没有人签到过喵~")
            return True
        sorted_users = sorted(
            _sign_data.items(), key=lambda x: x[1].get("points", 0), reverse=True
        )[:10]
        lines = ["签到排行榜 TOP10 喵~", "━━━━━━━━━━━━━━"]
        for i, (uid, info) in enumerate(sorted_users, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(
                f"{medal} {uid[:8]}... | {info.get('points', 0)}分 | 连签{info.get('streak', 0)}天"
            )
        lines.append("━━━━━━━━━━━━━━")
        await reply(ctx, "\n".join(lines))
        return True

    # 点歌（直接搜索）
    if re.match(r"^(点歌|听歌|来首歌)\s+.+", content):
        song_name = re.sub(r"^(点歌|听歌|来首歌)\s*[:：]?\s*", "", content).strip()
        if song_name:
            songs = await music.search_music(song_name)
            if songs:
                lines = [f"搜索到以下歌曲喵~回复序号选择："]
                for i, s in enumerate(songs[:5], 1):
                    lines.append(f"{i}. {s.get('name', '')} - {s.get('artist', '')}")
                _music_select[user_id] = {
                    "songs": songs[:5],
                    "ctx": ctx,
                    "ts": _time_mod.time(),
                }
                await reply_plain(ctx, "\n".join(lines))
            else:
                await reply(ctx, f"没有搜到「{song_name}」喵~")
            return True

    # 点歌（进入等待模式）
    if lower in ("点歌", "听歌", "来首歌"):
        _music_waiting[user_id] = {"ts": _time_mod.time(), "ctx": ctx}
        await reply(ctx, "请输入歌名喵~（60秒内有效）")
        return True

    # GitHub 搜索
    gh_match = re.match(r"^(搜索github|github搜|搜索gh)\s+(.+)", content, re.IGNORECASE)
    if gh_match:
        keyword = gh_match.group(2).strip()
        repos = await github.search_repos(keyword)
        if repos:
            lines = [f"GitHub 搜索「{keyword}」结果喵~回复序号查看详情："]
            for i, r in enumerate(repos[:5], 1):
                lines.append(f"{i}. {r.get('full_name', '')} ⭐{r.get('stars', 0)}")
            _github_select[user_id] = {
                "repos": repos[:5],
                "ctx": ctx,
                "ts": _time_mod.time(),
            }
            await reply_plain(ctx, "\n".join(lines))
        else:
            await reply(ctx, f"没有搜到「{keyword}」相关仓库喵~")
        return True

    # /ad 广告管理
    ad_match = re.match(r"^/ad(s?\+|s?-|)\s*(.*)", content or "", re.DOTALL)
    if ad_match:
        from datetime import datetime

        action = ad_match.group(1)
        payload = ad_match.group(2).strip()

        if not action:
            _ad_waiting[user_id] = _time_mod.time() + 300
            lines = ["当前广告列表喵~", "━━━━━━━━━━━━━━"]
            for ad in _ads:
                status = "展示中" if ad.get("enabled") else "未展示"
                lines.append(f"[{ad.get('id')}] {status}\n{ad.get('content', '')}")
            lines.append("━━━━━━━━━━━━━━")
            lines.append("用法：/ad+ 内容 | /ad- 编号 | /ads+ 编号 [时间] | /ads- 编号")
            await reply_plain(ctx, "\n".join(lines))
            return True

        if action == "+":
            if not payload:
                await reply_plain(ctx, "用法：/ad+ 广告内容")
                return True
            new_id = max((ad.get("id", 0) for ad in _ads), default=0) + 1
            _ads.append(
                {
                    "id": new_id,
                    "content": payload,
                    "enabled": False,
                    "active_until": None,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            _save_ads()
            await reply_plain(
                ctx,
                f"已新增广告 [{new_id}] 到列表喵~（未展示）\n使用 /ads+ {new_id} 开启展示",
            )
            return True

        if action == "-":
            target = None
            for ad in _ads:
                if str(ad.get("id")) == payload:
                    target = ad
                    break
            if not target:
                for ad in _ads:
                    if ad.get("content", "") == payload:
                        target = ad
                        break
            if not target:
                await reply_plain(ctx, "没有找到这个广告喵~请用编号")
                return True
            _ads.remove(target)
            _save_ads()
            await reply_plain(ctx, f"已删除广告 [{target.get('id')}] 喵~")
            return True

        if action == "s+":
            if _ad_waiting.get(user_id, 0) <= _time_mod.time():
                await reply_plain(ctx, "请先输入 /ad 查看列表")
                return True
            selector = payload.split()[0] if payload else ""
            target = None
            for ad in _ads:
                if str(ad.get("id")) == selector:
                    target = ad
                    break
            if not target:
                for ad in _ads:
                    if ad.get("content", "") == selector:
                        target = ad
                        break
            if not target:
                await reply_plain(ctx, "没有找到这个广告喵~")
                return True
            target["enabled"] = True
            # 解析时间
            time_part = (
                payload[len(selector) :].strip() if len(payload) > len(selector) else ""
            )
            if time_part:
                m = re.fullmatch(r"(\d+)(m|h|d)", time_part.lower())
                if m:
                    val = int(m.group(1))
                    unit = m.group(2)
                    secs = val * (60 if unit == "m" else 3600 if unit == "h" else 86400)
                    target["active_until"] = _time_mod.time() + secs
            else:
                target["active_until"] = None
            _save_ads()
            await reply_plain(ctx, f"已开始展示广告 [{target.get('id')}] 喵~")
            return True

        if action == "s-":
            if _ad_waiting.get(user_id, 0) <= _time_mod.time():
                await reply_plain(ctx, "请先输入 /ad 查看列表")
                return True
            target = None
            for ad in _ads:
                if str(ad.get("id")) == payload:
                    target = ad
                    break
            if not target:
                for ad in _ads:
                    if ad.get("content", "") == payload:
                        target = ad
                        break
            if not target:
                await reply_plain(ctx, "没有找到这个广告喵~请用编号")
                return True
            target["enabled"] = False
            target["active_until"] = None
            _save_ads()
            await reply_plain(ctx, f"已移除展示广告 [{target.get('id')}] 喵~")
            return True

        return True

    return False


async def handle_plugin(ctx, content):
    """Run enabled plugins after built-in commands and before AI fallback."""
    result = await plugin_runtime.dispatch({"ctx": ctx, "content": content})
    if not result:
        return False

    reply_text = result.get("reply")
    if reply_text:
        await reply(ctx, str(reply_text))
    return True


# ====== 链接解析 ======
async def check_links(ctx, content):
    """检查消息中的 B站/抖音/网页链接"""
    # 抖音
    dy_url = douyin.extract_douyin_url(content)
    if dy_url and _feature_enabled("builtin.douyin"):
        info = await douyin.get_video_info(dy_url)
        if info:
            await reply(ctx, info.get("text", "解析失败"))
        return True

    # B站
    bili_id = bilibili.extract_bilibili_id(content)
    if bili_id and _feature_enabled("builtin.bilibili"):
        info = await bilibili.get_video_info(bili_id)
        if info:
            await reply(ctx, info.get("text", "解析失败"))
        return True

    # 网页链接
    url = web_crawler.extract_url(content)
    if url and _feature_enabled("builtin.web_crawler"):
        await reply(ctx, f"检测到链接，正在分析喵...\n{url}")
        try:
            ok, html = await web_crawler.fetch_page(url)
            if ok:
                page = web_crawler.extract_content(html, url)
                title = page.get("title", "")
                desc = page.get("description", "")
                text = page.get("text", "")[:500]
                summary = f"网页标题：{title}\n描述：{desc}\n\n内容摘要：\n{text}"
                chat_id = f"web_{ctx['user_openid']}"
                ai_reply = await ai_chat.chat(
                    chat_id, f"请分析这个网页的内容：\n{summary}"
                )
                await reply(ctx, ai_reply)
            else:
                await reply(ctx, f"网页抓取失败喵：{html}")
        except Exception as e:
            await reply(ctx, f"网页分析出错喵：{e}")
        return True

    return False


# ====== 天气 ======
async def check_weather(ctx, content):
    if not _feature_enabled("builtin.fun"):
        return False
    match = re.match(r"^(.{1,10}?)天气$", content)
    if match:
        city = match.group(1)
        try:
            result = fun.get_weather(city)
            await reply(ctx, result)
        except Exception:
            await reply(ctx, f"获取 {city} 天气失败喵~")
        return True
    return False


# ====== 消息入口 ======
async def process_message(ctx, content):
    """统一消息处理入口"""
    if not content:
        await reply(ctx, "喵？你叫我了吗~")
        return

    user_id = ctx["user_openid"]
    now = _time_mod.time()

    # 0a. 点歌选择状态
    sel = _music_select.get(user_id)
    if sel and now - sel.get("ts", 0) < 120 and content.isdigit():
        if not _feature_enabled("builtin.music"):
            del _music_select[user_id]
            await _reply_feature_disabled(ctx, "点歌")
            return
        idx = int(content)
        songs = sel.get("songs", [])
        if 1 <= idx <= len(songs):
            song = songs[idx - 1]
            del _music_select[user_id]
            share = f"歌曲：{song.get('name', '')}\n歌手：{song.get('artist', '')}\n链接：{song.get('url', '')}"
            await reply(ctx, share)
            return
        else:
            del _music_select[user_id]
            await reply(ctx, "序号不对哦，点歌已取消喵~")
            return

    # 0b. GitHub 选择状态
    gsel = _github_select.get(user_id)
    if gsel and now - gsel.get("ts", 0) < 120 and content.isdigit():
        if not _feature_enabled("builtin.github"):
            del _github_select[user_id]
            await _reply_feature_disabled(ctx, "GitHub 搜索")
            return
        idx = int(content)
        repos = gsel.get("repos", [])
        if 1 <= idx <= len(repos):
            repo = repos[idx - 1]
            del _github_select[user_id]
            detail = github.build_repo_detail(repo)
            await reply(ctx, detail)
            return
        else:
            del _github_select[user_id]
            await reply(ctx, "序号不对哦，搜索已取消喵~")
            return

    # 0c. 点歌等待输入歌名
    mw = _music_waiting.get(user_id)
    if mw and now - mw.get("ts", 0) < 60:
        if not _feature_enabled("builtin.music"):
            del _music_waiting[user_id]
            await _reply_feature_disabled(ctx, "点歌")
            return
        del _music_waiting[user_id]
        songs = await music.search_music(content)
        if songs:
            lines = ["搜索到以下歌曲喵~回复序号选择："]
            for i, s in enumerate(songs[:5], 1):
                lines.append(f"{i}. {s.get('name', '')} - {s.get('artist', '')}")
            _music_select[user_id] = {"songs": songs[:5], "ctx": ctx, "ts": now}
            await reply_plain(ctx, "\n".join(lines))
        else:
            await reply(ctx, f"没有搜到「{content}」喵~")
        return
    elif mw:
        del _music_waiting[user_id]

    # 0d. 模糊指令确认
    fw = _fuzzy_waiting.get(user_id)
    if fw and now < fw.get("expire", 0):
        lowered = content.strip().lower()
        if lowered == "y":
            del _fuzzy_waiting[user_id]
            real_cmd = fw["command"]
            _log.info(f"[模糊指令] 确认执行: {real_cmd}")
            await handle_command(ctx, real_cmd)
            return
        if lowered in ("n", "no", "取消", "算了"):
            del _fuzzy_waiting[user_id]
            await reply(ctx, "好的喵~已取消")
            return
    if fw:
        del _fuzzy_waiting[user_id]

    # 1. 指令
    if await handle_command(ctx, content):
        return

    # 2. 插件指令
    if await handle_plugin(ctx, content):
        return

    # 3. 天气
    if await check_weather(ctx, content):
        return

    # 4. 链接解析
    if await check_links(ctx, content):
        return

    # 5. 模糊指令匹配（非已知指令才触发）
    if content.lower().strip() not in _KNOWN_COMMANDS:
        fuzzy = _find_fuzzy(content)
        if fuzzy:
            cmd, desc = fuzzy
            _fuzzy_waiting[user_id] = {"command": cmd, "ctx": ctx, "expire": now + 60}
            await reply_plain(
                ctx, f"你是不是想输入 {cmd} 呀？（{desc}）\n回复 y 确认执行喵~"
            )
            return

    # 6. AI 对话
    if not _feature_enabled("builtin.ai_chat"):
        return
    chat_id = f"{ctx['type']}_{user_id}"
    ai_reply = await ai_chat.chat(chat_id, content)
    if len(ai_reply) > 2000:
        ai_reply = ai_reply[:2000] + "\n...(内容过长已截断)"
    await reply(ctx, ai_reply)


# ====== 事件处理 ======
async def handle_group_message(data):
    group_openid = data.get("group_openid", "")
    msg_id = data.get("id", "")
    user_openid = data.get("author", {}).get("member_openid", "")
    content = data.get("content", "").strip()

    _log.info(f"[群消息] {user_openid[:8]}...: {content[:50]}")

    ctx = {
        "type": "group",
        "group_openid": group_openid,
        "user_openid": user_openid,
        "msg_id": msg_id,
    }
    await process_message(ctx, content)


async def handle_c2c_message(data):
    user_openid = data.get("author", {}).get("user_openid", "")
    msg_id = data.get("id", "")
    content = data.get("content", "").strip()

    _log.info(f"[私聊] {user_openid[:8]}...: {content[:50]}")

    ctx = {
        "type": "c2c",
        "group_openid": "",
        "user_openid": user_openid,
        "msg_id": msg_id,
    }
    await process_message(ctx, content)


# ====== WebSocket ======
async def get_gateway_url():
    headers = await get_gateway_auth_header()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}/gateway", headers=headers)
        if resp.status_code != 200:
            _log.warning(f"[Gateway] {resp.status_code}: {resp.text[:300]}")
        url = resp.json().get("url", "")
        _log.info(f"[Gateway] {url}")
        return url


async def run_websocket():
    reconnect_delay = 5
    session_id = ""
    last_seq = None

    while True:
        try:
            await refresh_access_token()
            gateway_url = await get_gateway_url()
            if not gateway_url:
                _log.error("[Gateway] 失败，5s 后重试")
                await asyncio.sleep(5)
                continue

            async with websockets.connect(
                gateway_url, max_size=10 * 1024 * 1024, ping_interval=None
            ) as ws:
                _log.info("[WS] 已连接")
                heartbeat_interval = 0
                heartbeat_task = None

                async def send_heartbeat():
                    while True:
                        await asyncio.sleep(heartbeat_interval / 1000)
                        await ws.send(json.dumps({"op": 1, "d": last_seq}))

                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        op, t, d, s = (
                            msg.get("op"),
                            msg.get("t"),
                            msg.get("d", {}),
                            msg.get("s"),
                        )
                        if s is not None:
                            last_seq = s

                        if op == 10:
                            heartbeat_interval = d.get("heartbeat_interval", 41250)
                            _log.info(f"[WS] Hello, hb={heartbeat_interval}ms")
                            if session_id and last_seq is not None:
                                await ws.send(
                                    json.dumps(
                                        {
                                            "op": 6,
                                            "d": {
                                                "token": f"QQBot {_access_token}",
                                                "session_id": session_id,
                                                "seq": last_seq,
                                            },
                                        }
                                    )
                                )
                            else:
                                await ws.send(
                                    json.dumps(
                                        {
                                            "op": 2,
                                            "d": {
                                                "token": f"QQBot {_access_token}",
                                                "intents": (1 << 25),
                                                "shard": [0, 1],
                                            },
                                        }
                                    )
                                )
                            heartbeat_task = asyncio.create_task(send_heartbeat())
                            reconnect_delay = 5

                        elif op == 0:
                            if t == "READY":
                                session_id = d.get("session_id", "")
                                _log.info(
                                    f"[WS] Ready! {d.get('user', {}).get('username', '?')}"
                                )
                            elif t == "RESUMED":
                                _log.info("[WS] Resumed")
                            elif t == "GROUP_AT_MESSAGE_CREATE":
                                asyncio.create_task(handle_group_message(d))
                            elif t == "C2C_MESSAGE_CREATE":
                                asyncio.create_task(handle_c2c_message(d))
                            elif t in (
                                "GROUP_ADD_ROBOT",
                                "GROUP_DEL_ROBOT",
                                "FRIEND_ADD",
                                "FRIEND_DEL",
                            ):
                                _log.info(f"[事件] {t}")
                            else:
                                _log.debug(f"[WS] {t}")

                        elif op == 11:
                            pass
                        elif op == 7:
                            _log.warning("[WS] 要求重连")
                            break
                        elif op == 9:
                            _log.warning("[WS] Session 失效")
                            session_id = ""
                            last_seq = None
                            break
                finally:
                    if heartbeat_task:
                        heartbeat_task.cancel()

        except websockets.exceptions.ConnectionClosed as e:
            _log.warning(f"[WS] 断开: {e}")
        except Exception as e:
            _log.error(f"[WS] 异常: {e}")

        _log.info(f"[WS] {reconnect_delay}s 后重连")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 1.5, 60)


async def token_refresh_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            await refresh_access_token()
        except Exception as e:
            _log.warning(f"[Auth] 刷新失败: {e}")


async def main():
    _log.info("=" * 50)
    _log.info("QQ 官方 Bot 全功能版启动")
    _log.info(f"AppID: {APP_ID} | v{BOT_VERSION}")
    _log.info(
        f"环境: {'沙箱' if SANDBOX else '正式'} | AI: {AI_CONFIG.get('model', '?')}"
    )
    _log.info("=" * 50)
    await refresh_access_token()
    await asyncio.gather(run_websocket(), token_refresh_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("Bot 已停止")
