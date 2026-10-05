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
import math
import re
import random
import time as _time_mod
import yaml
import httpx
import websockets
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from difflib import SequenceMatcher
from collections import OrderedDict

# 共享冷却
import shared_cooldown as _shared_cd
from state_backend import LocalStateBackend, build_state_backend

from adapters.qq_official import (
    C2C_MESSAGE_CREATE,
    GROUP_AT_MESSAGE_CREATE,
    GROUP_MESSAGE_EVENTS,
    adapt_message_event,
)
from adapters.koishi_bridge import adapt_koishi_payload
from handlers.ai_chat import AIChat
from handlers.image_gen import (
    GeneratedImage,
    ImageGenerator,
    extract_image_prompt,
    is_image_request,
)
from handlers import nfa, sauth, bjd, hypban, web_crawler
from handlers import fun, bilibili, douyin, music, github
from handlers import email_sender

# ====== 版本 ======
BOT_VERSION = "1.2.0"
BOT_BUILD_DATE = "2026-10-05"
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
IMAGE_AI_CONFIG = config.get("image_ai", {})
EMAIL_CONFIG = config.get("email", {})
BRIDGE_CONFIG = config.get("bridge", {})
CONTROL_CONFIG = config.get("control_api", {})


def _config_string_set(value) -> set[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not value:
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _config_value(section: dict, key: str, env_name: str | None = None, default=None):
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value is not None and str(env_value).strip():
            return str(env_value).strip()
    return section.get(key, default)


def _ai_config_value(section, key: str, env_name: str | None = None, default=None):
    if not isinstance(section, dict):
        section = {}
    config_value = section.get(key)
    if config_value is not None and str(config_value).strip():
        return str(config_value).strip()
    return _config_value(section, key, env_name, default)


def _ai_config_bool(
    section: dict, key: str, env_name: str | None = None, default: bool = False
) -> bool:
    value = _ai_config_value(section, key, env_name, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _ai_config_int(
    section: dict, key: str, env_name: str | None = None, default: int = 0
) -> int:
    try:
        return int(_ai_config_value(section, key, env_name, default))
    except (TypeError, ValueError):
        return int(default)


def _config_bool(
    section: dict, key: str, env_name: str | None = None, default: bool = False
) -> bool:
    value = _config_value(section, key, env_name, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _full_message_group_ids(section: dict) -> set[str]:
    return (
        _config_string_set(section.get("full_message_group_ids", []))
        | _config_string_set(section.get("non_at_group_whitelist", []))
        | _config_string_set(os.environ.get("QQ_GROUP_WHITELIST", ""))
    )


APP_ID = _config_value(BOT_CONFIG, "app_id", "QQ_APP_ID")
APP_SECRET = _config_value(BOT_CONFIG, "app_secret", "QQ_APP_SECRET")
SANDBOX = BOT_CONFIG.get("sandbox", False)
ADMIN_SECRET = config.get("admin_secret", "miracle2026")
API_BASE = (
    "https://sandbox.api.sgroup.qq.com" if SANDBOX else "https://api.sgroup.qq.com"
)
AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"
FULL_MESSAGE_GROUP_IDS = _full_message_group_ids(BOT_CONFIG)
GATEWAY_INTENTS = int(_config_value(BOT_CONFIG, "intents", "QQ_INTENTS", 1 << 25))
OFFICIAL_WS_ENABLED = _config_bool(
    BOT_CONFIG, "official_ws_enabled", "QQ_OFFICIAL_WS_ENABLED", True
)
BRIDGE_ENABLED = _config_bool(BRIDGE_CONFIG, "enabled", "QQ_BRIDGE_ENABLED", False)
BRIDGE_HOST = str(BRIDGE_CONFIG.get("host", "127.0.0.1"))
BRIDGE_PORT = int(BRIDGE_CONFIG.get("port", 8765))
BRIDGE_TOKEN = str(BRIDGE_CONFIG.get("token", ""))
MARKDOWN_ENABLED = _config_bool(
    BOT_CONFIG, "markdown_enabled", "QQ_MARKDOWN_ENABLED", True
)
QQ_WEBHOOK_PATH = str(_config_value(BOT_CONFIG, "webhook_path", "QQ_WEBHOOK_PATH", "/qq") or "/qq")
if not QQ_WEBHOOK_PATH.startswith("/"):
    QQ_WEBHOOK_PATH = "/" + QQ_WEBHOOK_PATH
CONTROL_API_BASE_URL = str(
    _config_value(CONTROL_CONFIG, "base_url", "CONTROL_API_BASE_URL", "") or ""
)
BOT_CONTROL_TOKEN = str(
    _config_value(CONTROL_CONFIG, "bot_token", "BOT_CONTROL_TOKEN", "") or ""
)
AI_BASE_URL = str(
    _ai_config_value(AI_CONFIG, "base_url", "AI_BASE_URL", "https://fisx-ai.guimc.ltd/v1")
    or ""
)
AI_API_KEY = str(_ai_config_value(AI_CONFIG, "api_key", "AI_API_KEY", "") or "")
AI_MODEL = str(_ai_config_value(AI_CONFIG, "model", "AI_MODEL", "deepseek-v4-flash") or "")
AI_CONFIG["base_url"] = AI_BASE_URL
AI_CONFIG["api_key"] = AI_API_KEY
AI_CONFIG["model"] = AI_MODEL
IMAGE_AI_ENABLED = _ai_config_bool(
    IMAGE_AI_CONFIG, "enabled", "IMAGE_AI_ENABLED", False
)
IMAGE_AI_BASE_URL = str(
    _ai_config_value(IMAGE_AI_CONFIG, "base_url", "IMAGE_AI_BASE_URL", "") or ""
)
IMAGE_AI_API_KEY = str(
    _ai_config_value(IMAGE_AI_CONFIG, "api_key", "IMAGE_AI_API_KEY", "") or ""
)
IMAGE_AI_MODEL = str(
    _ai_config_value(
        IMAGE_AI_CONFIG,
        "model",
        "IMAGE_AI_MODEL",
        "grok-imagine-1.0-fast",
    )
    or ""
)
IMAGE_AI_SIZE = str(
    _ai_config_value(IMAGE_AI_CONFIG, "size", "IMAGE_AI_SIZE", "1024x1024")
    or "1024x1024"
)
IMAGE_AI_COOLDOWN_SECONDS = max(
    0,
    _ai_config_int(
        IMAGE_AI_CONFIG,
        "cooldown_seconds",
        "IMAGE_AI_COOLDOWN_SECONDS",
        60,
    ),
)

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
    return _state_backend.is_admin(user_openid)


def _is_admin_or_staff(user_openid: str) -> bool:
    return _state_backend.is_admin_or_staff(user_openid)


def _is_banned(user_openid: str) -> bool:
    return _state_backend.is_banned(user_openid)


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

_state_backend = build_state_backend(CONTROL_API_BASE_URL, BOT_CONTROL_TOKEN)
if isinstance(_state_backend, LocalStateBackend):
    _state_backend.bind_memory(
        admin_set=_admin_set,
        staff=_staff,
        staff_logged_in=_staff_logged_in,
        banned_set=_banned_set,
        email_binds=_email_binds,
        save_admins=lambda: _save_json_set(ADMIN_FILE, _admin_set),
        save_staff=_save_staff_dict,
        save_banned=lambda: _save_json_set(BAN_FILE, _banned_set),
        save_email_binds=_save_email_binds,
    )
_log.info(f"[State] backend={_state_backend.backend_name}")


def _first_token(content: str) -> str:
    parts = str(content or "").strip().split()
    return parts[0].lower() if parts else ""


def _record_seen_user(ctx: dict) -> None:
    try:
        _state_backend.seen_user(
            ctx.get("user_openid", ""),
            group_openid=ctx.get("group_openid", ""),
        )
    except AttributeError:
        return
    except Exception as e:
        _log.warning(f"[ControlLog] seen_user failed: {e}")


def _log_command_event(ctx: dict, content: str) -> None:
    try:
        _state_backend.log_command(
            user_key=ctx.get("user_openid", ""),
            group_openid=ctx.get("group_openid", ""),
            command=_first_token(content),
            content=str(content or ""),
            message_id=ctx.get("msg_id", ""),
        )
    except AttributeError:
        return
    except Exception as e:
        _log.warning(f"[ControlLog] command failed: {e}")


def _log_outbound_event(
    ctx: dict,
    channel: str,
    ok: bool,
    content: str,
    message_id: str | None = None,
) -> None:
    try:
        _state_backend.log_outbound(
            user_key=ctx.get("user_openid", ""),
            group_openid=ctx.get("group_openid", ""),
            channel=channel,
            status="success" if ok else "failed",
            content=str(content or ""),
            message_id=message_id or ctx.get("msg_id", ""),
        )
    except AttributeError:
        return
    except Exception as e:
        _log.warning(f"[ControlLog] outbound failed: {e}")


def _log_email_outbound(
    ctx: dict,
    user_id: str,
    ok: bool,
    subject: str,
    masked_addr: str,
) -> None:
    try:
        _state_backend.log_outbound(
            user_key=user_id,
            group_openid=ctx.get("group_openid", ""),
            channel="email",
            status="success" if ok else "failed",
            content=f"{subject} -> {masked_addr}",
            message_id=ctx.get("msg_id", ""),
        )
    except AttributeError:
        return
    except Exception as e:
        _log.warning(f"[ControlLog] email failed: {e}")


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_QQ_NUMBER_RE = re.compile(r"^[1-9]\d{4,11}$")


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


def _qq_number_to_email(value: str) -> str:
    qq_number = (value or "").strip()
    if not _QQ_NUMBER_RE.match(qq_number):
        return ""
    return f"{qq_number}@qq.com"


def _get_bound_email(user_id: str) -> str:
    return _state_backend.get_email_binding(user_id)


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


def _resource_request_requires_email(ctx) -> bool:
    return ctx.get("type") != "c2c"


async def _send_resource_result(
    ctx,
    user_id: str,
    resource_key: str,
    resource_label: str,
    subject: str,
    result: str,
    quota_text: str = "",
) -> bool:
    to_addr = _get_bound_email(user_id)
    delivery_body = _append_quota_text(result, quota_text)

    if ctx.get("type") == "c2c":
        direct_body = _append_full_ads_to_email(delivery_body)
        ok = await reply(ctx, direct_body)
        if ok:
            return True
        if not to_addr:
            _log.warning(f"[{resource_key}] 私聊发送失败且未绑定邮箱 -> {user_id[:8]}...")
            return False

        ok, err = await _send_result_email(to_addr, subject, direct_body)
        masked_addr = _mask_email_addr(to_addr)
        _log_email_outbound(ctx, user_id, ok, subject, masked_addr)
        if ok:
            return True

        _log.warning(f"[{resource_key}] 私聊发送失败，邮箱兜底也失败 -> {masked_addr}: {err}")
        return False

    if not to_addr:
        await _require_bound_email(ctx, user_id)
        return False

    email_body = _append_full_ads_to_email(delivery_body)
    ok, err = await _send_result_email(to_addr, subject, email_body)
    masked_addr = _mask_email_addr(to_addr)
    _log_email_outbound(ctx, user_id, ok, subject, masked_addr)
    if ok:
        # The masking asterisks are literal text, not Markdown emphasis.
        display_addr = masked_addr.replace("*", r"\*") if MARKDOWN_ENABLED else masked_addr
        reply_text = f"{resource_label} 已发送到邮箱 {display_addr}，请查收喵~"
        if quota_text.strip():
            reply_text += f"\n{quota_text.strip()}"
        await reply(ctx, reply_text)
        return True

    _log.warning(f"[{resource_key}] 邮件发送失败 -> {masked_addr}: {err}")
    await reply(ctx, f"{resource_label} 邮件发送失败，请检查绑定邮箱或稍后再试喵~")
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
image_generator = ImageGenerator(
    base_url=IMAGE_AI_BASE_URL,
    api_key=IMAGE_AI_API_KEY,
    model=IMAGE_AI_MODEL,
    size=IMAGE_AI_SIZE,
)
_image_cooldowns: dict[str, float] = {}

# ====== 冷却/频率常量 ======
NFA_COOLDOWN = 1800
_NFA_HOUR_LIMIT = 5
_NFA_BAN_DURATION = 86400
_163_HOUR_LIMIT = 5
_163_BAN_DURATION = 86400

_RESTRICT_FEATURES = {"163", "4399", "nfa"}
_RESTRICT_UNITS = {"min", "hour", "day", "month", "quarter", "year"}
_active_resource_request_keys: set[str] = set()


def _resource_request_key(feature: str, user_id: str, ctx: dict) -> str:
    chat_type = str(ctx.get("type") or "unknown").lower()
    chat_id = str(ctx.get("group_openid") or ctx.get("user_openid") or user_id)
    return f"{str(feature).lower()}:{chat_type}:{chat_id}:{user_id}"


def _begin_resource_request(feature: str, user_id: str, ctx: dict) -> bool:
    key = _resource_request_key(feature, user_id, ctx)
    if key in _active_resource_request_keys:
        return False
    _active_resource_request_keys.add(key)
    return True


def _end_resource_request(feature: str, user_id: str, ctx: dict) -> None:
    _active_resource_request_keys.discard(_resource_request_key(feature, user_id, ctx))

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


def _parse_restrict_command(content: str) -> tuple[str, int, str] | None:
    parts = content.strip().split()
    if len(parts) != 4 or parts[0].lower() != "/restrict":
        return None
    feature = parts[1].lower()
    unit = parts[3].lower()
    if feature not in _RESTRICT_FEATURES or unit not in _RESTRICT_UNITS:
        return None
    try:
        limit = int(parts[2])
    except ValueError:
        return None
    if limit <= 0:
        return None
    return feature, limit, unit


def _format_duration_cn(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    if seconds <= 0:
        return "0s"
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}min")
    parts.append(f"{seconds}s")
    return "".join(parts)


def _resource_quota_line(status: dict) -> str:
    limit = int(status.get("limit", 0) or 0)
    if limit <= 0:
        return ""
    count = int(status.get("count", 0) or 0)
    return f"当前获取：{count}/{limit}"


def _resource_quota_text(status: dict, include_reset: bool = False) -> str:
    lines = []
    quota_line = _resource_quota_line(status)
    if quota_line:
        lines.append(quota_line)
    reset_after = int(status.get("reset_after", 0) or 0)
    if include_reset and reset_after:
        lines.append(f"限额刷新：{_format_duration_cn(reset_after)}")
    return "\n".join(lines)


def _append_quota_text(body: str, quota_text: str = "") -> str:
    quota_text = str(quota_text or "").strip()
    if not quota_text:
        return body
    return body.rstrip() + "\n\n" + quota_text


async def _check_resource_restrict(ctx: dict, feature: str, user_id: str) -> dict | None:
    status = _state_backend.get_resource_limit_status(feature, user_id)
    if status.get("blocked"):
        quota_text = _resource_quota_text(status, include_reset=True)
        lines = ["已达到获取上限"]
        if quota_text:
            lines.append(quota_text)
        await reply(ctx, "\n".join(lines))
        return None
    return status


def _record_resource_restrict(feature: str, user_id: str) -> None:
    _state_backend.record_resource_usage(feature, user_id)


def _resource_success_quota_line(feature: str, user_id: str) -> str:
    status = _state_backend.get_resource_limit_status(feature, user_id)
    return _resource_quota_text(status, include_reset=True)

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
    "sauth",
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
    "/sauth",
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
    ("4399", "获取 4399 账号密码"),
    ("sauth", "只获取 4399 Sauth"),
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


def _refresh_ads_from_file():
    global _ads
    _ads = _load_ads()
    changed = _expire_ads_in_place(_ads)
    if changed:
        _save_ads()
    return _ads


def _expire_ads_in_place(ads: list[dict]) -> bool:
    now = _time_mod.time()
    changed = False
    for ad in ads:
        until = ad.get("active_until")
        if ad.get("enabled") and isinstance(until, (int, float)) and until <= now:
            ad["enabled"] = False
            changed = True
    return changed


def _get_active_ads():
    _refresh_ads_from_file()
    now = _time_mod.time()
    result = []
    changed = False
    for ad in _ads:
        if not ad.get("enabled"):
            continue
        until = ad.get("active_until")
        if isinstance(until, (int, float)) and until <= now:
            ad["enabled"] = False
            changed = True
            continue
        result.append(ad.get("content", ""))
    if changed:
        _save_ads()
    return result


def _append_ads(text):
    ads = _get_active_ads()
    if not ads:
        return text
    ad = random.choice(ads)
    return f"{text}\n\n━━━ 广告 ━━━\n{ad}"


def _append_full_ads_to_email(body: str) -> str:
    ads = _get_active_ads()
    if not ads:
        return body
    lines = ["", "━━━━━━━━━━━━━━", "完整赞助信息"]
    for index, ad in enumerate(ads, start=1):
        lines.append(f"{index}. {ad}")
    return body.rstrip() + "\n\n" + "\n".join(lines)


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
        token = data.get("access_token")
        if not token:
            body = json.dumps(data, ensure_ascii=False)[:500]
            raise RuntimeError(
                f"Auth response missing access_token: status={resp.status_code} body={body}"
            )
        _access_token = token
        expires_in = int(data.get("expires_in", 7200))
        _token_expire_at = _time_mod.time() + expires_in - 60
        _log.info(f"[Auth] access_token 有效期 {expires_in}s")


async def get_auth_header():
    if _time_mod.time() >= _token_expire_at:
        await refresh_access_token()
    return _build_bot_auth_header()


def _build_bot_auth_header():
    return {
        "Authorization": f"QQBot {_access_token}",
        "X-Union-Appid": APP_ID,
        "Content-Type": "application/json",
    }


def _build_gateway_auth_header():
    return {
        "Authorization": f"Bearer {_access_token}",
        "X-Union-Appid": APP_ID,
        "Content-Type": "application/json",
    }


async def get_gateway_auth_header():
    if _time_mod.time() >= _token_expire_at:
        await refresh_access_token()
    return _build_gateway_auth_header()


# ====== 消息发送 ======
_msg_seq_counter: dict[str, int] = {}
_INBOUND_GROUP_MSG_CACHE_MAX = 1000
_recent_group_msg_ids: OrderedDict[str, float] = OrderedDict()
_recent_c2c_msg_ids: OrderedDict[str, float] = OrderedDict()


def _remember_inbound_message(
    cache: OrderedDict[str, float], scope: str, msg_id: str
) -> bool:
    if not msg_id:
        return True

    key = f"{scope}:{msg_id}"
    if key in cache:
        return False

    cache[key] = _time_mod.time()
    while len(cache) > _INBOUND_GROUP_MSG_CACHE_MAX:
        cache.popitem(last=False)
    return True


def _remember_group_message(group_openid: str, msg_id: str) -> bool:
    return _remember_inbound_message(_recent_group_msg_ids, group_openid, msg_id)


def _remember_c2c_message(user_openid: str, msg_id: str) -> bool:
    return _remember_inbound_message(_recent_c2c_msg_ids, user_openid, msg_id)


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


def _next_msg_seq(key: str) -> int:
    _msg_seq_counter[key] = _msg_seq_counter.get(key, 0) + 1
    return _msg_seq_counter[key]


def _build_text_payload(content: str, msg_id: str, msg_seq: int) -> dict:
    return {
        "content": content,
        "msg_type": 0,
        "msg_id": msg_id,
        "msg_seq": msg_seq,
    }


def _build_markdown_payload(
    content: str, msg_id: str, msg_seq: int, keyboard: dict | None = None
) -> dict:
    payload = {
        "msg_type": 2,
        "markdown": {"content": _normalize_message_start(content)},
        "msg_id": msg_id,
        "msg_seq": msg_seq,
    }
    if keyboard:
        payload["keyboard"] = keyboard
    return payload


def _normalize_message_start(content: str) -> str:
    """Remove empty leading lines/BOM without damaging Markdown indentation."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"\A(?:(?:[^\S\n]|[\u200b\ufeff])*\n)+", "", content)
    return content.lstrip("\u200b\ufeff")


def _build_send_payload(
    content: str,
    msg_id: str,
    msg_seq: int,
    markdown: bool,
    keyboard: dict | None = None,
) -> dict:
    if markdown and MARKDOWN_ENABLED:
        return _build_markdown_payload(content, msg_id, msg_seq, keyboard)
    return _build_text_payload(content, msg_id, msg_seq)


def _command_button(
    button_id: str,
    label: str,
    command: str,
    style: int = 1,
) -> dict:
    return {
        "id": button_id,
        "render_data": {
            "label": label,
            "visited_label": label,
            "style": style,
        },
        "action": {
            "type": 2,
            "data": command,
            "enter": True,
            "reply": False,
            "permission": {"type": 2},
        },
    }


def _default_resource_keyboard() -> dict:
    return _build_inline_keyboard(
        [
            [
                _command_button("quick_4399", "获取4399", "/4399", 1),
                _command_button("quick_sauth", "获取Sauth", "/sauth", 1),
                _command_button("quick_163", "获取163", "/163", 1),
            ],
            [
                _command_button("quick_stock", "查询库存", "/查库存", 1),
                _command_button("quick_bind", "快捷绑定", "/bind", 1),
            ]
        ]
    )


def _build_inline_keyboard(rows: list[list[dict]]) -> dict:
    return {
        "content": {
            "rows": [{"buttons": row[:5]} for row in rows[:5] if row],
        }
    }


def _status_ok(status_code: int) -> bool:
    return status_code in (200, 201, 202, 204)


async def _post_with_markdown_fallback(
    client,
    url: str,
    headers: dict,
    key: str,
    content: str,
    msg_id: str,
    log_prefix: str,
    keyboard: dict | None = None,
) -> bool:
    content = _normalize_message_start(content)
    body = _build_send_payload(
        content, msg_id, _next_msg_seq(key), markdown=True, keyboard=keyboard
    )
    resp = await client.post(url, headers=headers, json=body)
    if _status_ok(resp.status_code):
        return True

    if MARKDOWN_ENABLED and body.get("msg_type") == 2:
        _log.warning(
            f"{log_prefix} Markdown失败 {resp.status_code}: {resp.text[:200]}，降级文本"
        )
        fallback_body = _build_send_payload(
            content, msg_id, _next_msg_seq(key), markdown=False
        )
        resp = await client.post(url, headers=headers, json=fallback_body)
        if _status_ok(resp.status_code):
            return True

    _log.warning(f"{log_prefix} 失败 {resp.status_code}: {resp.text[:200]}")
    return False


async def send_group_msg(group_openid, content, msg_id, keyboard: dict | None = None):
    content = _sanitize_url(content)
    if len(content) > 2000:
        content = content[:2000] + "\n...(内容过长已截断)"
    if keyboard is None:
        keyboard = _default_resource_keyboard()
    headers = await get_auth_header()
    key = f"g_{group_openid}_{msg_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return await _post_with_markdown_fallback(
                client,
                f"{API_BASE}/v2/groups/{group_openid}/messages",
                headers,
                key,
                content,
                msg_id,
                "[发送] 群消息",
                keyboard,
            )
    except Exception as e:
        _log.error(f"[发送] 群消息异常: {e}")
        return False


async def send_c2c_msg(user_openid, content, msg_id, keyboard: dict | None = None):
    content = _sanitize_url(content)
    if len(content) > 2000:
        content = content[:2000] + "\n...(内容过长已截断)"
    if keyboard is None:
        keyboard = _default_resource_keyboard()
    headers = await get_auth_header()
    key = f"c_{user_openid}_{msg_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return await _post_with_markdown_fallback(
                client,
                f"{API_BASE}/v2/users/{user_openid}/messages",
                headers,
                key,
                content,
                msg_id,
                "[发送] 私聊",
                keyboard,
            )
    except Exception as e:
        _log.error(f"[发送] 私聊异常: {e}")
        return False


def _build_media_upload_payload(image: GeneratedImage) -> dict:
    payload = {"file_type": 1, "srv_send_msg": False}
    if image.url:
        payload["url"] = image.url
    elif image.b64_json:
        payload["file_data"] = image.b64_json
    else:
        raise ValueError("image has no content")
    return payload


def _build_media_message_payload(file_info: str, msg_id: str, msg_seq: int) -> dict:
    return {
        "msg_type": 7,
        "media": {"file_info": file_info},
        "msg_id": msg_id,
        "msg_seq": msg_seq,
    }


async def _send_image(
    *, target_type: str, target_id: str, image: GeneratedImage, msg_id: str
) -> bool:
    if target_type == "group":
        base_url = f"{API_BASE}/v2/groups/{target_id}"
        key = f"g_{target_id}_{msg_id}"
        log_prefix = "[AI生图] 群图片"
    else:
        base_url = f"{API_BASE}/v2/users/{target_id}"
        key = f"c_{target_id}_{msg_id}"
        log_prefix = "[AI生图] 私聊图片"

    try:
        upload_payload = _build_media_upload_payload(image)
    except ValueError:
        _log.warning("%s 缺少图片内容", log_prefix)
        return False

    headers = await get_auth_header()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            upload = await client.post(
                f"{base_url}/files", headers=headers, json=upload_payload
            )
            if not _status_ok(upload.status_code):
                _log.warning("%s 上传失败 HTTP %s", log_prefix, upload.status_code)
                return False
            try:
                upload_result = upload.json()
            except (TypeError, ValueError):
                _log.warning("%s 上传响应格式无效", log_prefix)
                return False
            file_info = (
                str(upload_result.get("file_info") or "").strip()
                if isinstance(upload_result, dict)
                else ""
            )
            if not file_info:
                _log.warning("%s 上传响应缺少 file_info", log_prefix)
                return False

            response = await client.post(
                f"{base_url}/messages",
                headers=headers,
                json=_build_media_message_payload(
                    file_info, msg_id, _next_msg_seq(key)
                ),
            )
            if not _status_ok(response.status_code):
                _log.warning("%s 发送失败 HTTP %s", log_prefix, response.status_code)
                return False
            return True
    except Exception as exc:
        _log.warning("%s 异常: %s", log_prefix, type(exc).__name__)
        return False


async def send_group_image(group_openid, image: GeneratedImage, msg_id):
    return await _send_image(
        target_type="group",
        target_id=group_openid,
        image=image,
        msg_id=msg_id,
    )


async def send_c2c_image(user_openid, image: GeneratedImage, msg_id):
    return await _send_image(
        target_type="c2c",
        target_id=user_openid,
        image=image,
        msg_id=msg_id,
    )


# ====== 统一回复 ======
async def reply(ctx, text):
    if ctx["type"] == "group":
        ok = await send_group_msg(ctx["group_openid"], text, ctx["msg_id"])
        _log_outbound_event(ctx, "group", ok, text)
    else:
        ok = await send_c2c_msg(ctx["user_openid"], text, ctx["msg_id"])
        _log_outbound_event(ctx, "c2c", ok, text)
    return ok


async def reply_image(ctx, image: GeneratedImage):
    if ctx["type"] == "group":
        ok = await send_group_image(ctx["group_openid"], image, ctx["msg_id"])
        channel = "group"
    else:
        ok = await send_c2c_image(ctx["user_openid"], image, ctx["msg_id"])
        channel = "c2c"
    _log_outbound_event(ctx, channel, ok, "[AI 生图图片]")
    return ok


async def reply_markdown_card(ctx, markdown: str, button_rows: list[list[dict]]):
    keyboard = _build_inline_keyboard(button_rows)
    if ctx["type"] == "group":
        ok = await send_group_msg(
            ctx["group_openid"], markdown, ctx["msg_id"], keyboard=keyboard
        )
        _log_outbound_event(ctx, "group", ok, markdown)
    else:
        ok = await send_c2c_msg(
            ctx["user_openid"], markdown, ctx["msg_id"], keyboard=keyboard
        )
        _log_outbound_event(ctx, "c2c", ok, markdown)
    return ok


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

    ok = False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            ok = await _post_with_markdown_fallback(
                client,
                url,
                headers,
                key,
                text,
                ctx["msg_id"],
                "[发送plain]",
            )
    except Exception as e:
        _log.error(f"[发送plain] 异常: {e}")
    finally:
        _log_outbound_event(ctx, "group" if ctx["type"] == "group" else "c2c", ok, text)
    return ok


# ====== 指令处理 ======
async def handle_command(ctx, content):
    """处理所有指令，返回 True 表示已处理"""
    lower = content.lower().strip()
    user_id = ctx["user_openid"]
    limit_user_id = ctx.get("limit_user_id") or user_id

    if lower in ("/mdtest", "mdtest"):
        await reply_markdown_card(
            ctx,
            (
                "## Markdown 测试\n\n"
                "服务：**Official QQBot**\n"
                "这是一条 Markdown 卡片测试消息。\n"
                f"ID:{ctx.get('msg_id', '')}\n\n"
                "> 如果下方按钮能显示，说明 keyboard 也生效。"
            ),
            [
                [
                    _command_button("mdtest_status", "查看状态", "/status", 1),
                    _command_button("mdtest_stock", "查看库存", "/stock", 1),
                    _command_button("mdtest_help", "帮助", "/help", 1),
                ]
            ],
        )
        return True

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
                "4399 — 获取 4399 账号密码\n"
                "sauth — 只获取 4399 Sauth\n"
                "163 — 领取 163 小号\n"
                "stock — 查看全部库存\n"
                "/bind 邮箱/QQ号 — 绑定资源接收地址（群聊领取前必需）\n"
                "/unbind — 取消邮箱绑定\n"
                "━━━ 查询功能 ━━━\n"
                "bjd — 查询布吉岛版本\n"
                "hypban — Hypixel 封禁统计\n"
                "status — 运行状态\n"
                "datalog — 完整更新日志\n"
                "/whois — 查看自己的 openid\n"
                "━━━ AI 对话 ━━━\n"
                "@我 + 任意内容 — AI 聊天\n"
                "/生图 描述 — 生成一张图片\n"
                "也可直接说：帮我画一张……\n"
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
                "群聊可直接发送指令；AI 聊天请 @我。私聊直接发消息即可喵~"
            ),
        )
        return True

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
            _state_backend.add_admin(user_id)
            await reply_plain(
                ctx, "验证成功喵~您已成为管理员！\n授权已持久化，重启后无需重新验证~"
            )
            _log.info(f"[Auth] {user_id[:8]}... 成为 admin")
            return True

        # staff 密码验证
        if _state_backend.staff_exists(user_id):
            staff_password = _state_backend.get_staff_password(user_id)
            if not staff_password:
                _state_backend.set_staff_password(user_id, code)
                _state_backend.login_staff(user_id)
                await reply_plain(
                    ctx, f"Staff 密码设置成功喵~已登陆！\n（密码：{code}）"
                )
                _log.info(f"[Staff] {user_id[:8]}... 激活")
                return True
            if staff_password == code:
                _state_backend.login_staff(user_id)
                await reply_plain(ctx, "Staff 登陆成功喵~")
                _log.info(f"[Staff] {user_id[:8]}... 登陆")
                return True

        await reply_plain(ctx, "验证码不正确喵~")
        return True

    # ===== /quit =====
    if lower in ("/quit", "quit"):
        removed = _state_backend.logout(user_id)
        await reply_plain(ctx, "已退出登陆喵~" if removed else "您当前没有登陆状态喵~")
        return True

    # ===== /admin 面板 =====
    if lower in ("/admin", "admin"):
        if not _is_admin(user_id):
            await reply(ctx, "需要管理权限喵~请先私聊 /auth 验证码")
            return True
        counts = _state_backend.counts()
        admin_count = counts["admins"]
        staff_count = counts["staff"]
        ban_count = counts["banned"]
        lines = [
            f"曦曦官方Bot 管理面板",
            f"━━━━━━━━━━━━━━",
            f"管理员：{admin_count} 人",
            f"Staff：{staff_count} 人（在线 {counts['staff_online']}）",
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

    if lower.startswith("/restrict"):
        if not _is_admin_or_staff(user_id):
            await reply(ctx, "需要管理权限喵~")
            return True
        parsed = _parse_restrict_command(content)
        if not parsed:
            await reply(
                ctx,
                "用法：/restrict 163/4399/nfa 数量 时间\n时间支持：min hour day month quarter year",
            )
            return True
        feature, limit, unit = parsed
        _state_backend.set_resource_limit(feature, limit, unit, updated_by=user_id)
        await reply_plain(ctx, f"已设置 {feature} 每个用户 {unit} 内最多获取 {limit} 个")
        return True

    if lower == "/resetlimit":
        if not _is_admin_or_staff(user_id):
            await reply(ctx, "需要管理权限喵~")
            return True
        _state_backend.reset_resource_usage()
        await reply_plain(ctx, "已重置所有用户的获取限制记录，/restrict 规则保持不变")
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
        _state_backend.ban_user(target)
        await reply_plain(ctx, f"已封禁 {target[:12]}... 喵~")
        _log.info(f"[Ban] {user_id[:8]}... 封禁了 {target[:12]}...")
        return True

    # ===== /unban =====
    if content.startswith("/unban "):
        if not _is_admin_or_staff(user_id):
            await reply(ctx, "需要管理权限喵~")
            return True
        target = content[7:].strip()
        if not _state_backend.is_banned(target):
            await reply(ctx, "该用户不在封禁列表中喵~")
            return True
        _state_backend.unban_user(target)
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
        if _state_backend.staff_exists(target):
            await reply(ctx, "该用户已是 Staff 喵~")
            return True
        _state_backend.add_staff(target, added_by=user_id[:12])
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
        if not _state_backend.staff_exists(target):
            await reply(ctx, "该用户不是 Staff 喵~")
            return True
        _state_backend.delete_staff(target)
        await reply_plain(ctx, f"已移除 Staff {target[:12]}... 喵~")
        _log.info(f"[Staff] {user_id[:8]}... 移除了 {target[:12]}...")
        return True

    # ===== /whois 查看用户 openid =====
    if lower in ("/whois", "whois"):
        email = _state_backend.get_email_binding(user_id) or "未绑定"
        await reply_plain(ctx, f"你的 openid：\n{user_id}\n绑定邮箱：{email}")
        return True

    # ===== 绑定邮箱 =====
    bind_match = re.match(r"^(?:/bind|绑定邮箱|/绑定邮箱|绑定QQ号|绑定qq号|/bindqq)\s+(\S+)$", content, re.IGNORECASE)
    if bind_match:
        bind_target = bind_match.group(1)
        email = _normalize_email_addr(bind_target)
        if ctx.get("type") == "c2c" and not _is_valid_email_addr(email):
            email = _qq_number_to_email(bind_target)
        if not _is_valid_email_addr(email):
            await reply(
                ctx,
                "格式不对喵~请输入：/bind 你的邮箱地址\n私聊也可以输入：/bind 你的QQ号\n例如：/bind 123456@qq.com",
            )
            return True
        _state_backend.set_email_binding(user_id, email)
        await reply_plain(
            ctx, f"邮箱绑定成功喵~\n{email}\n之后领取 nfa/4399/163 会自动发到这个邮箱！"
        )
        _log.info(f"[邮箱] {user_id[:8]}... 绑定 {email}")
        return True

    if lower in ("/bind", "bind", "绑定邮箱", "/绑定邮箱", "绑邮箱") or re.match(
        r"^(?:/bind|绑定邮箱|/绑定邮箱|绑定QQ号|绑定qq号|/bindqq)\s+", content, re.IGNORECASE
    ):
        await reply(
            ctx,
            "请输入：/bind 你的邮箱地址\n私聊也可以输入：/bind 你的QQ号\n例如：/bind 123456@qq.com\n绑定后才能领取 nfa/4399/163 喵~",
        )
        return True

    # ===== 解绑邮箱 =====
    if lower in ("/unbind", "unbind", "解绑邮箱", "/解绑邮箱", "取消邮箱"):
        if _state_backend.delete_email_binding(user_id):
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
        if _resource_request_requires_email(ctx) and not await _require_bound_email(ctx, user_id):
            return True
        if not await _check_resource_restrict(ctx, "nfa", limit_user_id):
            return True

        banned, bh, bm = _shared_cd.is_banned("nfa", limit_user_id)
        if banned:
            await reply(
                ctx, f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~"
            )
            return True
        in_cd, remain = _shared_cd.check_cooldown("nfa", limit_user_id, NFA_COOLDOWN)
        if in_cd:
            await reply(
                ctx, f"获取太频繁啦喵~请 {remain // 60}分{remain % 60}秒 后再试~"
            )
            return True
        over, count = _shared_cd.check_hour_limit(
            "nfa", limit_user_id, _NFA_HOUR_LIMIT, _NFA_BAN_DURATION
        )
        if over:
            await reply(
                ctx, f"一小时内频繁获取NFA（{count}次），疑似偷卡，已封禁24小时喵~"
            )
            return True
        _shared_cd.record_usage("nfa", limit_user_id)
        result = await nfa.get_nfa_token("admin", "zutomayo0.")
        if "主人您的nfa来了喵" in result:
            _record_resource_restrict("nfa", limit_user_id)
            quota_text = _resource_success_quota_line("nfa", limit_user_id)
            result += "\n爱来自Miracle nfa bot喵~"
            await _send_resource_result(
                ctx,
                user_id,
                "NFA",
                "NFA",
                "Miracle NFA Token",
                result,
                quota_text=quota_text,
            )
        else:
            await reply(ctx, result)
        _log.info(f"[NFA] {user_id[:8]}...")
        return True

    # 4399
    if lower in ("4399", "/4399"):
        if _resource_request_requires_email(ctx) and not await _require_bound_email(ctx, user_id):
            return True
        if not await _check_resource_restrict(ctx, "4399", limit_user_id):
            return True

        if not _begin_resource_request("4399", limit_user_id, ctx):
            _log.info(f"[ResourceDedup] 4399 busy user={limit_user_id[:8]}...")
            return True

        success, result = await sauth.get_4399_credentials()
        if success:
            _record_resource_restrict("4399", limit_user_id)
            quota_text = _resource_success_quota_line("4399", limit_user_id)
            result += "\n爱来自Miracle小号网站喵~"
            await _send_resource_result(
                ctx,
                user_id,
                "4399",
                "4399 账号",
                "Miracle 4399 账号密码",
                result,
                quota_text=quota_text,
            )
        else:
            await reply(ctx, result)
        _log.info(f"[4399] {user_id[:8]}...")
        _end_resource_request("4399", limit_user_id, ctx)
        return True

    # sauth
    if lower in ("sauth", "/sauth"):
        if _resource_request_requires_email(ctx) and not await _require_bound_email(ctx, user_id):
            return True
        if not await _check_resource_restrict(ctx, "4399", limit_user_id):
            return True

        if not _begin_resource_request("4399", limit_user_id, ctx):
            _log.info(f"[ResourceDedup] sauth busy user={limit_user_id[:8]}...")
            return True

        success, result = await sauth.get_sauth()
        if success:
            _record_resource_restrict("4399", limit_user_id)
            quota_text = _resource_success_quota_line("4399", limit_user_id)
            await _send_resource_result(
                ctx,
                user_id,
                "sauth",
                "4399 Sauth",
                "Miracle 4399 Sauth",
                result,
                quota_text=quota_text,
            )
        else:
            await reply(ctx, result)
        _log.info(f"[Sauth] {user_id[:8]}...")
        _end_resource_request("4399", limit_user_id, ctx)
        return True

    # 163
    if lower in ("163", "/163"):
        if _resource_request_requires_email(ctx) and not await _require_bound_email(ctx, user_id):
            return True
        if not await _check_resource_restrict(ctx, "163", limit_user_id):
            return True

        banned, bh, bm = _shared_cd.is_banned("163", limit_user_id)
        if banned:
            await reply(
                ctx, f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~"
            )
            return True
        in_cd, remain = _shared_cd.check_cooldown("163", limit_user_id, 60)
        if in_cd:
            await reply(ctx, f"一分钟内已获取过啦，请{remain}秒后再试喵~")
            return True
        over, count = _shared_cd.check_hour_limit(
            "163", limit_user_id, _163_HOUR_LIMIT, _163_BAN_DURATION
        )
        if over:
            await reply(
                ctx, f"一小时内频繁获取（{count}次），疑似偷卡，已封禁24小时喵~"
            )
            return True

        if not _begin_resource_request("163", limit_user_id, ctx):
            _log.info(f"[ResourceDedup] 163 busy user={limit_user_id[:8]}...")
            return True

        _shared_cd.record_usage("163", limit_user_id)

        success, result_163 = await sauth.get_163_credentials()
        if success:
            _record_resource_restrict("163", limit_user_id)
            quota_text = _resource_success_quota_line("163", limit_user_id)
            await _send_resource_result(
                ctx,
                user_id,
                "163",
                "163 小号",
                "Miracle 163 小号",
                result_163,
                quota_text=quota_text,
            )
        else:
            await reply(ctx, result_163)
        _end_resource_request("163", limit_user_id, ctx)
        return True

    # stock
    if lower in ("stock", "/stock", "查库存", "/查库存"):
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
            ok163, avail163, total163, used163, _ = await sauth.get_163_stock()
            lines.append(
                f"163：{avail163}/{total163}" if ok163 else "163：unavailable"
            )
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

        _refresh_ads_from_file()
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


# ====== 链接解析 ======
async def check_links(ctx, content):
    """检查消息中的 B站/抖音/网页链接"""
    # 抖音
    dy_url = douyin.extract_douyin_url(content)
    if dy_url:
        info = await douyin.get_video_info(dy_url)
        if info:
            await reply(ctx, info.get("text", "解析失败"))
        return True

    # B站
    bili_id = bilibili.extract_bilibili_id(content)
    if bili_id:
        info = await bilibili.get_video_info(bili_id)
        if info:
            await reply(ctx, info.get("text", "解析失败"))
        return True

    # 网页链接
    url = web_crawler.extract_url(content)
    if url:
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


async def handle_image_request(ctx, content):
    if not is_image_request(content):
        return False

    prompt = extract_image_prompt(content)
    if not prompt:
        await reply(ctx, "请在 /生图 后面填写图片描述\n例如：/生图 雨夜里的重庆")
        return True
    if not IMAGE_AI_ENABLED:
        await reply(ctx, "AI 生图尚未启用，请联系管理员")
        return True
    if not image_generator.configured:
        await reply(ctx, "AI 生图尚未配置，请联系管理员")
        return True

    user_key = str(ctx.get("limit_user_id") or ctx["user_openid"])
    now = _time_mod.monotonic()
    ready_at = _image_cooldowns.get(user_key, 0) + IMAGE_AI_COOLDOWN_SECONDS
    if now < ready_at:
        remaining = math.ceil(ready_at - now)
        await reply(ctx, f"AI 生图冷却中，还需 {remaining} 秒")
        return True

    _image_cooldowns[user_key] = now
    await reply(ctx, f"## AI 生图\n\n正在生成：**{prompt}**\n\n请稍候……")
    image, error = await image_generator.generate(prompt)
    if not image:
        await reply(ctx, error or "图片生成失败，请稍后再试")
        return True
    if not await reply_image(ctx, image):
        await reply(ctx, "图片已经生成，但发送到 QQ 失败，请稍后重试")
    return True


# ====== 消息入口 ======
def _pending_for_context(states, ctx):
    pending = states.get(ctx["user_openid"])
    if not pending:
        return None
    origin = pending.get("ctx", {})
    if (origin.get("type"), origin.get("group_openid", "")) != (
        ctx.get("type"), ctx.get("group_openid", "")
    ):
        return None
    return pending


def _is_group_command(ctx, content):
    """Only explicit commands and same-conversation follow-ups trigger full events."""
    content = content.strip()
    if not content:
        return False
    lower = content.lower()
    if lower.startswith("/") or lower in _KNOWN_COMMANDS or lower in {
        "mdtest", "auth", "quit", "admin", "whois", "unbind", "绑邮箱", "取消邮箱", "查库存",
    }:
        return True
    if re.match(
        r"^(?:auth|点歌|听歌|来首歌|搜索github|github搜|搜索gh|绑定邮箱|绑定qq号)\s+",
        content, re.IGNORECASE,
    ) or re.fullmatch(r".{1,10}天气", content):
        return True
    if re.match(r"^(?:生图|绘图)(?:\s|$)", content):
        return True
    now = _time_mod.time()
    for states in (_music_select, _github_select):
        pending = _pending_for_context(states, ctx)
        if pending and now - pending.get("ts", 0) < 120 and content.isdigit():
            return True
    pending = _pending_for_context(_music_waiting, ctx)
    if pending and now - pending.get("ts", 0) < 60:
        return True
    pending = _pending_for_context(_fuzzy_waiting, ctx)
    return bool(pending and now < pending.get("expire", 0) and lower in {"y", "n", "no", "取消", "算了"})


async def process_message(ctx, content):
    """统一消息处理入口"""
    image_urls = tuple(ctx.get("image_urls") or ())
    commands_only = bool(ctx.get("commands_only"))
    if commands_only and not _is_group_command(ctx, content):
        return
    if not content and not image_urls:
        await reply(ctx, "喵？你叫我了吗~")
        return

    user_id = ctx["user_openid"]
    _record_seen_user(ctx)
    now = _time_mod.time()

    # 0a. 点歌选择状态
    sel = _pending_for_context(_music_select, ctx)
    if sel and now - sel.get("ts", 0) < 120 and content.isdigit():
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
    gsel = _pending_for_context(_github_select, ctx)
    if gsel and now - gsel.get("ts", 0) < 120 and content.isdigit():
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
    mw = _pending_for_context(_music_waiting, ctx)
    if mw and now - mw.get("ts", 0) < 60:
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
    fw = _pending_for_context(_fuzzy_waiting, ctx)
    if fw and now < fw.get("expire", 0):
        lowered = content.strip().lower()
        if lowered == "y":
            del _fuzzy_waiting[user_id]
            real_cmd = fw["command"]
            _log.info(f"[模糊指令] 确认执行: {real_cmd}")
            handled = await handle_command(ctx, real_cmd)
            if handled:
                _log_command_event(ctx, real_cmd)
            return
        if lowered in ("n", "no", "取消", "算了"):
            del _fuzzy_waiting[user_id]
            await reply(ctx, "好的喵~已取消")
            return
    if fw:
        del _fuzzy_waiting[user_id]

    # 1. 指令
    if await handle_command(ctx, content):
        _log_command_event(ctx, content)
        return

    # 2. 天气
    if await check_weather(ctx, content):
        return

    # 3. 链接解析
    if not commands_only and await check_links(ctx, content):
        return

    # 4. AI 生图
    if await handle_image_request(ctx, content):
        _log_command_event(ctx, content)
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
    if commands_only:
        return
    chat_id = f"{ctx['type']}_{user_id}"
    ai_reply = await ai_chat.chat(chat_id, content, image_urls=image_urls)
    if len(ai_reply) > 2000:
        ai_reply = ai_reply[:2000] + "\n...(内容过长已截断)"
    await reply(ctx, ai_reply)


# ====== 事件处理 ======
async def handle_group_message(data, event_type=GROUP_AT_MESSAGE_CREATE):
    event = adapt_message_event(event_type, data, FULL_MESSAGE_GROUP_IDS)
    if not event:
        _log.debug(
            f"[群消息忽略] event={event_type} group={data.get('group_openid', '')}"
        )
        return

    if event.is_full_message and not event.is_at and not _is_group_command(event.to_ctx(), event.content):
        return

    if not _remember_group_message(event.group_openid, event.msg_id):
        _log.debug(
            f"[群消息去重] event={event.event_type} "
            f"group={event.group_openid} msg={event.msg_id}"
        )
        return

    _log.info(
        f"[群消息] event={event.event_type} group={event.group_openid} "
        f"user={event.user_openid[:8]}... images={len(event.image_urls)}: "
        f"{event.content[:50]}"
    )
    await process_message(event.to_ctx(), event.content)


async def handle_c2c_message(data):
    event = adapt_message_event(C2C_MESSAGE_CREATE, data, FULL_MESSAGE_GROUP_IDS)
    if not event:
        return

    if not _remember_c2c_message(event.user_openid, event.msg_id):
        _log.debug(f"[私聊去重] user={event.user_openid[:8]}... msg={event.msg_id}")
        return

    _log.info(
        f"[私聊] {event.user_openid[:8]}... images={len(event.image_urls)}: "
        f"{event.content[:50]}"
    )
    await process_message(event.to_ctx(), event.content)


async def handle_koishi_bridge_payload(payload: dict):
    event = adapt_koishi_payload(payload, FULL_MESSAGE_GROUP_IDS)
    if not event:
        return {"ok": True, "ignored": True}

    if event.is_full_message and not event.is_at and not _is_group_command(event.to_ctx(), event.content):
        return {"ok": True, "ignored": True}

    if event.type == "group" and not _remember_group_message(
        event.group_openid, event.msg_id
    ):
        _log.debug(
            f"[KoishiBridge去重] group={event.group_openid} msg={event.msg_id}"
        )
        return {"ok": True, "ignored": True, "reason": "duplicate"}
    if event.type == "c2c" and not _remember_c2c_message(
        event.user_openid, event.msg_id
    ):
        _log.debug(
            f"[KoishiBridge鍘婚噸] user={event.user_openid[:8]}... msg={event.msg_id}"
        )
        return {"ok": True, "ignored": True, "reason": "duplicate"}
    _log.info(
        f"[KoishiBridge] type={event.type} group={event.group_openid} "
        f"user={event.user_openid[:8]}... images={len(event.image_urls)}: "
        f"{event.content[:50]}"
    )
    await process_message(event.to_ctx(), event.content)
    return {"ok": True, "ignored": False}


def _qq_webhook_key(app_secret: str):
    secret_bytes = str(app_secret or "").encode("utf-8")
    if not secret_bytes:
        raise ValueError("QQ_APP_SECRET is required for webhook validation")
    while len(secret_bytes) < 32:
        secret_bytes = (secret_bytes + secret_bytes)[:32]
    return ed25519.Ed25519PrivateKey.from_private_bytes(secret_bytes[:32])


def _build_qq_webhook_signature(app_secret: str, event_ts: str, plain_token: str) -> str:
    key = _qq_webhook_key(app_secret)
    return key.sign(f"{event_ts}{plain_token}".encode("utf-8")).hex()


def _verify_qq_webhook(body: bytes, headers) -> bool:
    if APP_ID and headers.get("X-Bot-Appid", "") != str(APP_ID):
        return False
    timestamp = headers.get("X-Signature-Timestamp", "")
    signature = headers.get("X-Signature-Ed25519", "")
    if not timestamp or not signature:
        return False
    try:
        _qq_webhook_key(APP_SECRET).public_key().verify(
            bytes.fromhex(signature), timestamp.encode("utf-8") + body
        )
    except (ValueError, InvalidSignature):
        return False
    return True


async def _receive_qq_webhook(request):
    from aiohttp import web

    body = await request.read()
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return web.json_response({"status": "error", "error": "invalid_json"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"status": "error", "error": "invalid_payload"}, status=400)
    # QQ URL verification (op 13) uses the challenge/response handshake.
    # Dispatches must authenticate the exact bytes forwarded by the proxy.
    if APP_ID and request.headers.get("X-Bot-Appid", "") != str(APP_ID):
        _log.warning("[QQWebhook] rejected: invalid_appid")
        return web.json_response({"error": "invalid_appid"}, status=403)
    if payload.get("op") != 13 and not _verify_qq_webhook(body, request.headers):
        _log.warning("[QQWebhook] rejected: invalid_signature")
        return web.json_response({"error": "invalid_signature"}, status=403)
    try:
        result = await handle_qq_webhook_payload(payload)
    except Exception as error:
        _log.error(f"[QQWebhook] 处理失败: {error}")
        return web.json_response({"status": "error", "error": "handler_failed"}, status=500)
    return web.json_response(result)


async def handle_qq_webhook_payload(payload: dict, app_secret: str | None = None):
    if not isinstance(payload, dict):
        return {"status": "ignored", "reason": "invalid_payload"}

    data = payload.get("d", {})
    if payload.get("op") == 13 and isinstance(data, dict) and "event_ts" in data and "plain_token" in data:
        plain_token = str(data.get("plain_token", ""))
        event_ts = str(data.get("event_ts", ""))
        return {
            "plain_token": plain_token,
            "signature": _build_qq_webhook_signature(
                app_secret or APP_SECRET,
                event_ts,
                plain_token,
            ),
        }

    if payload.get("op") != 0:
        return {"status": "ignored", "reason": "unsupported_opcode"}
    event_type = str(payload.get("t") or payload.get("event_type") or "")
    if not isinstance(data, dict):
        data = {}

    if event_type in GROUP_MESSAGE_EVENTS:
        if event_type != GROUP_AT_MESSAGE_CREATE:
            _log.info(
                "[QQWebhook] dispatch=%s group_allowed=%s",
                event_type,
                not FULL_MESSAGE_GROUP_IDS or data.get("group_openid", "") in FULL_MESSAGE_GROUP_IDS,
            )
        await handle_group_message(data, event_type)
    elif event_type == C2C_MESSAGE_CREATE:
        await handle_c2c_message(data)
    elif event_type:
        _log.info(
            f"[QQWebhook] event={event_type} "
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
    else:
        _log.debug("[QQWebhook] ignored payload without event type")

    return {"status": "success"}


def _bridge_token_matches(expected: str, actual: str) -> bool:
    if not expected:
        return True
    return actual == expected


async def run_koishi_bridge_server():
    from aiohttp import web

    async def health(_request):
        return web.json_response({"ok": True})

    async def receive_message(request):
        if not _bridge_token_matches(
            BRIDGE_TOKEN, request.headers.get("X-Bridge-Token", "")
        ):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        result = await handle_koishi_bridge_payload(payload)
        return web.json_response(result)

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/koishi/message", receive_message)
    app.router.add_post(QQ_WEBHOOK_PATH, _receive_qq_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, BRIDGE_HOST, BRIDGE_PORT)
    await site.start()
    _log.info(
        f"[KoishiBridge] listening on http://{BRIDGE_HOST}:{BRIDGE_PORT}, "
        f"qq_webhook={QQ_WEBHOOK_PATH}"
    )

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


# ====== WebSocket ======
async def get_gateway_url():
    headers = await get_gateway_auth_header()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}/gateway/bot", headers=headers)
        if resp.status_code != 200:
            _log.warning(f"[Gateway] {resp.status_code}: {resp.text[:300]}")
            return ""
        url = resp.json().get("url", "")
        _log.info(f"[Gateway] {url}")
        return url


async def _send_heartbeat_once(ws, seq):
    try:
        await ws.send(json.dumps({"op": 1, "d": seq}))
        return True
    except Exception as e:
        _log.warning(f"[WS] 心跳发送失败，准备重连: {e}")
        try:
            await ws.close()
        except Exception as close_error:
            _log.debug(f"[WS] 心跳失败后关闭连接也失败: {close_error}")
        return False


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
                        if not await _send_heartbeat_once(ws, last_seq):
                            return

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
                                                "intents": GATEWAY_INTENTS,
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
                            elif t in GROUP_MESSAGE_EVENTS:
                                asyncio.create_task(handle_group_message(d, t))
                            elif t == C2C_MESSAGE_CREATE:
                                asyncio.create_task(handle_c2c_message(d))
                            elif t in (
                                "GROUP_ADD_ROBOT",
                                "GROUP_DEL_ROBOT",
                                "FRIEND_ADD",
                                "FRIEND_DEL",
                            ):
                                _log.info(f"[事件] {t}")
                            else:
                                if t:
                                    _log.info(
                                        f"[WS事件未处理] t={t} "
                                        f"keys={list(d.keys()) if isinstance(d, dict) else type(d).__name__} "
                                        f"group={d.get('group_openid', '') if isinstance(d, dict) else ''} "
                                        f"id={d.get('id', '') if isinstance(d, dict) else ''}"
                                    )
                                else:
                                    _log.debug(f"[WS] {t}")

                        elif op == 11:
                            pass
                        elif op == 7:
                            _log.warning("[WS] 要求重连")
                            break
                        elif op == 9:
                            _log.warning(f"[WS] Session 失效/鉴权失败: d={d}")
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


def _build_runtime_tasks(
    official_ws_enabled: bool = OFFICIAL_WS_ENABLED,
    bridge_enabled: bool = BRIDGE_ENABLED,
):
    tasks = [token_refresh_loop()]
    if official_ws_enabled:
        tasks.insert(0, run_websocket())
    if bridge_enabled:
        tasks.append(run_koishi_bridge_server())
    return tasks


async def main():
    _log.info("=" * 50)
    _log.info("QQ 官方 Bot 全功能版启动")
    _log.info(f"AppID: {APP_ID} | v{BOT_VERSION}")
    _log.info(
        f"环境: {'沙箱' if SANDBOX else '正式'} | AI: {AI_CONFIG.get('model', '?')}"
    )
    _log.info(
        f"AI 生图: {'启用' if IMAGE_AI_ENABLED else '关闭'} | "
        f"配置: {'完整' if image_generator.configured else '未完成'} | "
        f"模型: {IMAGE_AI_MODEL or '未配置'}"
    )
    _log.info(f"Gateway intents: {GATEWAY_INTENTS}")
    _log.info(f"Full group messages: commands only; groups={sorted(FULL_MESSAGE_GROUP_IDS) or 'all'}")
    _log.info(f"Official WS enabled: {OFFICIAL_WS_ENABLED}")
    _log.info(f"Bridge listener enabled: {BRIDGE_ENABLED}")
    _log.info("=" * 50)
    await refresh_access_token()
    await asyncio.gather(*_build_runtime_tasks())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("Bot 已停止")
