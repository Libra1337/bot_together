"""
QQ 机器人主程序
基于 NapCatQQ + OneBot v11 WebSocket 协议
支持关键词回复 + AI 智能对话 + 签到/运势/天气/入群欢迎
"""

import os
import sys
import json
import asyncio
import logging
import re
import platform
import time as _time_mod
import contextvars
from difflib import SequenceMatcher

import yaml
import websockets

from onebot_adapter import OneBotTransport
from onebot_message import (
    extract_at_qq as _extract_at_qq_impl,
    extract_text,
    is_at_me as _is_at_me_impl,
)

# ====== 版本信息 ======
BOT_VERSION = "3.3.0"
BOT_BUILD_DATE = "2026-04-15"
_start_time: float = _time_mod.time()  # 启动时间戳


def disable_quickedit():
    """禁用 Windows 控制台的 QuickEdit 模式，防止点击窗口导致程序冻结"""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32

        # STD_INPUT_HANDLE = -10
        handle = kernel32.GetStdHandle(ctypes.wintypes.DWORD(-10))
        if handle == -1:
            print("[QuickEdit] 获取控制台句柄失败")
            return

        # 获取当前控制台模式
        mode = ctypes.wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            print("[QuickEdit] GetConsoleMode 失败")
            return

        old_mode = mode.value

        # ENABLE_QUICK_EDIT_MODE = 0x0040
        # ENABLE_EXTENDED_FLAGS  = 0x0080
        # ENABLE_INSERT_MODE     = 0x0020
        new_mode = mode.value
        new_mode &= ~0x0040  # 关闭 QuickEdit
        new_mode &= ~0x0020  # 关闭 InsertMode（也可能触发选中冻结）
        new_mode |= 0x0080  # 必须开启 ExtendedFlags 才能让上面的设置生效

        if not kernel32.SetConsoleMode(handle, ctypes.wintypes.DWORD(new_mode)):
            print(f"[QuickEdit] SetConsoleMode 失败")
            return

        print(f"[QuickEdit] 已禁用 (0x{old_mode:04X} -> 0x{new_mode:04X})")
    except Exception as e:
        print(f"[QuickEdit] 异常: {e}")


disable_quickedit()

from handlers.message_handler import MessageHandler
from handlers.ai_chat import AIChat
from handlers import fun
from handlers import bilibili
from handlers import music
from handlers import github
from handlers import douyin
from handlers import nfa
from handlers import sauth
from handlers import bjd
from handlers import hypban
from handlers import web_crawler
from handlers import email_sender
from handlers import aircon

import sys as _sys

_bot_dir = os.path.dirname(os.path.abspath(__file__))
if _bot_dir not in _sys.path:
    _sys.path.insert(0, _bot_dir)
import shared_cooldown as _shared_cd

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("QQBot")
onebot = OneBotTransport(logger=_log, send_max_retries=3, send_retry_delays=[1, 2, 4])


def load_config(config_path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件"""
    if not os.path.exists(config_path):
        _log.error(f"配置文件 {config_path} 不存在！")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


# 加载配置
config = load_config()

# 初始化消息处理器（关键词回复）
handler = MessageHandler(
    replies=config.get("replies", []),
    default_reply=config.get("default_reply", ""),
)

# 初始化 AI 对话
ai_config = config.get("ai", {})

# 加载系统提示词
system_prompt = ai_config.get("system_prompt", "")
prompt_file = ai_config.get("system_prompt_file", "")
if prompt_file and os.path.exists(prompt_file):
    with open(prompt_file, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()
    _log.info(f"已从 {prompt_file} 加载系统提示词（{len(system_prompt)} 字）")

# 加载 API Keys
api_keys = ai_config.get("api_keys", [])
if not api_keys:
    single_key = ai_config.get("api_key", "")
    if single_key:
        api_keys = [single_key]

ai_chat = AIChat(
    base_url=ai_config.get("base_url", ""),
    api_keys=api_keys,
    model=ai_config.get("model", "gpt-3.5-turbo"),
    system_prompt=system_prompt,
    max_history=ai_config.get("max_history", 10),
)

# OneBot 连接配置
WS_URL = config.get("onebot", {}).get("ws_url", "ws://127.0.0.1:3001")
WS_TOKEN = config.get("onebot", {}).get("token", "")
BOT_QQ = config.get("bot_qq", 0)
GROUP_TRIGGER = config.get("group_trigger", "曦曦")
NOTIFY_QQ = config.get("notify_qq", 0)
VIP_QQ = config.get("vip_qq", 3510904661)  # VIP用户，消息优先处理
BJD_GROUPS = config.get("bjd_broadcast_groups", [])  # 撤回提醒通知的QQ号

# 消息缓存（用于撤回提醒，保存最近的消息）
from collections import OrderedDict
from datetime import datetime

_msg_cache: OrderedDict = OrderedDict()
MAX_CACHE = 300  # 缓存满 300 条时导出到 txt 并清空

# 消息缓存导出目录
MSG_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "msg_cache"
)
os.makedirs(MSG_CACHE_DIR, exist_ok=True)


def _export_msg_cache():
    """将当前消息缓存导出到 txt 文件，然后清空缓存"""
    if not _msg_cache:
        return
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(MSG_CACHE_DIR, f"cache_{now_str}.txt")
    try:
        lines = []
        for msg_id, info in _msg_cache.items():
            nickname = info.get("nickname", "未知")
            uid = info.get("user_id", 0)
            gid = info.get("group_id", 0)
            content = info.get("content", "")
            ts = info.get("time", "")
            line = f"[{ts}] msg_id={msg_id} | 群{gid} | {nickname}({uid}): {content}"
            lines.append(line)
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        count = len(_msg_cache)
        _msg_cache.clear()
        _log.info(f"[缓存导出] 已导出 {count} 条消息到 {filename}")
    except Exception as e:
        _log.warning(f"[缓存导出] 导出失败: {e}")


def _lookup_msg_from_files(msg_id: str) -> dict | None:
    """从已导出的 txt 文件中查找指定 msg_id 的消息"""
    try:
        files = sorted(
            [f for f in os.listdir(MSG_CACHE_DIR) if f.endswith(".txt")],
            reverse=True,
        )
        for fname in files:
            fpath = os.path.join(MSG_CACHE_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if f"msg_id={msg_id}" in line:
                        # 解析: [time] msg_id=xxx | 群gid | nickname(uid): content
                        parts = line.split(" | ", 2)
                        if len(parts) < 3:
                            continue
                        name_content = parts[2]
                        sep_idx = name_content.find("): ")
                        if sep_idx == -1:
                            continue
                        name_part = name_content[: sep_idx + 1]
                        content_part = name_content[sep_idx + 3 :]
                        paren_idx = name_part.rfind("(")
                        nickname = name_part[:paren_idx] if paren_idx > 0 else "未知"
                        return {"nickname": nickname, "content": content_part.strip()}
    except Exception as e:
        _log.debug(f"[缓存回顾] 查找文件失败: {e}")
    return None


# 点歌模式状态 {user_key: timestamp}  等待用户输入歌名（60s超时）
_music_waiting: dict[str, float] = {}

# 广播喊话状态 {user_key: {"step": "select_group"|"input_msg", "groups": [...], "selected": [...]}}
_hh_waiting: dict[str, dict] = {}

# 163 小号领取冷却 {user_id: last_timestamp}
_163_cooldown: dict[int, float] = {}
# 163 小号一小时内领取记录 {user_id: [timestamp, ...]}
_163_hour_log: dict[int, list[float]] = {}
# 163 偷卡封禁 {user_id: unban_timestamp}
_163_banned: dict[int, float] = {}
_163_HOUR_LIMIT = 5
_163_BAN_DURATION = 86400  # 24小时

# 模糊指令确认状态 {user_key: {command, info, expire}}
_command_hint_waiting: dict[str, dict] = {}

COMMAND_HINT_EXPIRE = 60

_FUZZY_COMMAND_SPECS = [
    {
        "command": "/auth",
        "exacts": {"/auth"},
        "prefixes": ["/auth ", "/auth:", "/auth："],
        "info": "指令说明：`/auth 验证码` 或 `/auth 密码`\n用途：管理员验证，或 Staff 激活/登录账号。",
    },
    {
        "command": "/quit",
        "exacts": {"/quit"},
        "prefixes": [],
        "info": "指令说明：`/quit`\n用途：退出当前管理员或 Staff 登录状态。",
    },
    {
        "command": "/admin",
        "exacts": {"/admin"},
        "prefixes": [],
        "info": "指令说明：`/admin`\n用途：查看管理员、Staff、封禁和 NFA 授权面板。",
    },
    {
        "command": "/staff",
        "exacts": {"/staff"},
        "prefixes": [],
        "info": "指令说明：`/staff`\n用途：查看 Staff 管理面板和可用管理指令。",
    },
    {
        "command": "/addstaff",
        "exacts": set(),
        "prefixes": ["/addstaff", "/add "],
        "info": "指令说明：`/addstaff QQ号` 或 `/addstaff @用户`\n用途：添加 Staff。",
    },
    {
        "command": "/deletestaff",
        "exacts": {"/deletestaff"},
        "prefixes": ["/deletestaff ", "/deletestaff:", "/deletestaff："],
        "info": "指令说明：`/deletestaff` 或 `/deletestaff QQ号`\n用途：移除 Staff。",
    },
    {
        "command": "/授权q",
        "exacts": set(),
        "prefixes": ["/授权q ", "/授权q:", "/授权q："],
        "info": "指令说明：`/授权q QQ号 功能`\n用途：为指定 QQ 授权功能（all/nfa/4399/163）。",
    },
    {
        "command": "/授权群",
        "exacts": set(),
        "prefixes": [
            "/授权群 ",
            "/授权群:",
            "/授权群：",
        ],
        "info": "指令说明：`/授权群 群号 功能`\n用途：为整群授权功能（all/nfa/4399/163）。",
    },
    {
        "command": "/取消授权",
        "exacts": set(),
        "prefixes": ["/取消授权 ", "/取消授权:", "/取消授权："],
        "info": "指令说明：`/取消授权 群号/QQ号`\n用途：取消指定群或个人的全部授权。",
    },
    {
        "command": "/ban",
        "exacts": set(),
        "prefixes": ["/ban ", "/ban:", "/ban："],
        "info": "指令说明：`/ban QQ号`\n用途：封禁用户，禁止其继续使用 Bot。",
    },
    {
        "command": "/unban",
        "exacts": set(),
        "prefixes": ["/unban ", "/unban:", "/unban："],
        "info": "指令说明：`/unban QQ号`\n用途：解除封禁用户。",
    },
    {
        "command": "/nfa",
        "exacts": {"/nfa"},
        "prefixes": [],
        "info": "指令说明：`/nfa`\n用途：获取 NFA Token，需要管理员或白名单权限。",
    },
    {
        "command": "/4399",
        "exacts": {"/4399"},
        "prefixes": [],
        "info": "指令说明：`/4399`\n用途：获取 4399 sauth。",
    },
    {
        "command": "/163",
        "exacts": {"/163"},
        "prefixes": [],
        "info": "指令说明：`/163`\n用途：领取 163 小号。",
    },
    {
        "command": "/stock",
        "exacts": {"/stock"},
        "prefixes": [],
        "info": "指令说明：`/stock`\n用途：查看 NFA、4399、163 全部库存。",
    },
    {
        "command": "/bind",
        "exacts": {"/bind", "/绑定邮箱"},
        "prefixes": ["/bind ", "/绑定邮箱 "],
        "info": "指令说明：`/bind 邮箱`\n用途：绑定 nfa/4399/163 资源接收邮箱。",
    },
    {
        "command": "/unbind",
        "exacts": {"/unbind", "/解绑邮箱"},
        "prefixes": [],
        "info": "指令说明：`/unbind`\n用途：解绑资源接收邮箱。",
    },
    {
        "command": "/ad",
        "exacts": {"/ad"},
        "prefixes": ["/ad+", "/ad-", "/ads+", "/ads-"],
        "info": "指令说明：`/ad`\n用途：管理广告列表与展示状态。",
    },
    {
        "command": "/bjd",
        "exacts": {"/bjd"},
        "prefixes": ["/bjdon", "/bjdoff"],
        "info": "指令说明：`/bjd`\n用途：查询布吉岛当前版本信息。\n`/bjdon` 开启定时播报\n`/bjdoff` 关闭定时播报",
    },
    {
        "command": "/hypban",
        "exacts": {"/hypban"},
        "prefixes": [],
        "info": "指令说明：`/hypban`\n用途：查询 Hypixel 封禁统计。",
    },
    {
        "command": "/hypban on",
        "exacts": {"/hypban on"},
        "prefixes": [],
        "info": "指令说明：`/hypban on`\n用途：在当前群开启每分钟自动播报。",
    },
    {
        "command": "/hypban off",
        "exacts": {"/hypban off"},
        "prefixes": [],
        "info": "指令说明：`/hypban off`\n用途：关闭当前群的自动播报。",
    },
    {
        "command": "/datalog",
        "exacts": {"/datalog"},
        "prefixes": [],
        "info": "指令说明：`/datalog`\n用途：查看完整更新日志。",
    },
    {
        "command": "/status",
        "exacts": {"/status"},
        "prefixes": [],
        "info": "指令说明：`/status`\n用途：查看 Bot 运行状态和当前版本摘要。",
    },
    {
        "command": "/shutdown",
        "exacts": {"/shutdown"},
        "prefixes": ["/shutdown "],
        "info": "指令说明：`/shutdown now`、`/shutdown -5`、`/shutdown -c`\n用途：立即关机、定时关机或取消计划关机。",
    },
    {
        "command": "/check",
        "exacts": {"/check"},
        "prefixes": [],
        "info": "指令说明：`/check`\n用途：查看 Bot 当前加入的群聊和好友数量。",
    },
    {
        "command": "/hh",
        "exacts": {"/hh"},
        "prefixes": ["/hh ", "/hh:", "/hh："],
        "info": "指令说明：`/hh` 或 `/hh all 内容`\n用途：进入选群广播，或直接全群广播。",
    },
    {
        "command": "/dashboard",
        "exacts": {"/dashboard"},
        "prefixes": [],
        "info": "指令说明：`/dashboard`\n用途：查看系统、QQ 和 Bot 仪表盘信息。",
    },
    {
        "command": "/showlottery",
        "exacts": {"/showlottery", "/查看奖品"},
        "prefixes": [],
        "info": "指令说明：`/showlottery`\n用途：查看当前抽奖奖品保险箱。",
    },
    {
        "command": "/jrrp",
        "exacts": {"/jrrp"},
        "prefixes": [],
        "info": "指令说明：`/jrrp`\n用途：查看今日人品。",
    },
]


def _command_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _get_command_token(content: str) -> str:
    return re.split(r"[\s:：]+", content.strip(), maxsplit=1)[0]


def _is_known_slash_command(content: str) -> bool:
    stripped = content.strip()
    for spec in _FUZZY_COMMAND_SPECS:
        if stripped in spec["exacts"]:
            return True
        if any(stripped.startswith(prefix) for prefix in spec["prefixes"]):
            return True
    return False


def _find_fuzzy_command(content: str) -> dict | None:
    stripped = content.strip()
    token = _get_command_token(stripped)
    best_spec = None
    best_score = 0.0

    for spec in _FUZZY_COMMAND_SPECS:
        command = spec["command"]
        texts = {command, *spec["exacts"]}
        score = max(_command_similarity(stripped, text) for text in texts)
        score = max(score, _command_similarity(token, command.split()[0]))

        if " " in command and " " in stripped:
            score = max(score, _command_similarity(stripped, command))

        if score > best_score:
            best_score = score
            best_spec = spec

    if best_score < 0.62:
        return None
    return best_spec


# Admin 授权用户集合（通过 /auth 验证后才能使用 /nfa、/shutdown 等管理指令）
ADMIN_AUTH_CODE = config.get("admin_auth_code", config.get("nfa_auth_code", "776392"))
ADMIN_AUTH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "admin_auth.json"
)
NFA_USER_AUTH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "nfa_user_auth.json"
)
NFA_GROUP_AUTH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "nfa_group_auth.json"
)


def _load_admin_authorized() -> set[int]:
    """从文件加载已授权的管理员列表"""
    try:
        if os.path.exists(ADMIN_AUTH_FILE):
            with open(ADMIN_AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            authorized = set(int(uid) for uid in data)
            if authorized:
                _log.info(f"[AUTH] 已恢复 {len(authorized)} 个管理员授权")
            return authorized
    except Exception as e:
        _log.warning(f"[AUTH] 加载授权文件失败: {e}")
    return set()


def _save_admin_authorized():
    """保存已授权的管理员列表到文件"""
    try:
        os.makedirs(os.path.dirname(ADMIN_AUTH_FILE), exist_ok=True)
        with open(ADMIN_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_admin_authorized), f)
    except Exception as e:
        _log.warning(f"[AUTH] 保存授权文件失败: {e}")


_admin_authorized: set[int] = _load_admin_authorized()


# 支持的功能列表
ALL_FEATURES = {"nfa", "4399", "163"}


def _load_nfa_user_authorized() -> dict[int, list[str]]:
    """从文件加载个人白名单"""
    try:
        if os.path.exists(NFA_USER_AUTH_FILE):
            with open(NFA_USER_AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧格式：纯列表 [qq1, qq2] → 自动迁移为 {qq: ["all"]}
            if isinstance(data, list):
                migrated = {int(uid): ["all"] for uid in data}
                _log.info(f"[授权] 迁移旧个人授权格式，{len(migrated)} 人 → all")
                authorized = migrated
            elif isinstance(data, dict):
                authorized = {int(k): v for k, v in data.items()}
            else:
                authorized = {}
            if authorized:
                _log.info(f"[授权] 已恢复 {len(authorized)} 个个人授权")
            return authorized
    except Exception as e:
        _log.warning(f"[授权] 加载个人授权文件失败: {e}")
    return {}


def _save_nfa_user_authorized():
    """保存个人授权白名单"""
    try:
        os.makedirs(os.path.dirname(NFA_USER_AUTH_FILE), exist_ok=True)
        with open(NFA_USER_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _nfa_user_authorized.items()}, f)
    except Exception as e:
        _log.warning(f"[授权] 保存个人授权文件失败: {e}")


_nfa_user_authorized: dict[int, list[str]] = _load_nfa_user_authorized()


def _load_nfa_group_authorized() -> dict[int, list[str]]:
    """从文件加载群白名单"""
    try:
        if os.path.exists(NFA_GROUP_AUTH_FILE):
            with open(NFA_GROUP_AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧格式：纯列表 [gid1, gid2] → 自动迁移为 {gid: ["all"]}
            if isinstance(data, list):
                migrated = {int(gid): ["all"] for gid in data}
                _log.info(f"[授权] 迁移旧群授权格式，{len(migrated)} 群 → all")
                authorized = migrated
            elif isinstance(data, dict):
                authorized = {int(k): v for k, v in data.items()}
            else:
                authorized = {}
            if authorized:
                _log.info(f"[授权] 已恢复 {len(authorized)} 个群授权")
            return authorized
    except Exception as e:
        _log.warning(f"[授权] 加载群授权文件失败: {e}")
    return {}


def _save_nfa_group_authorized():
    """保存群授权白名单"""
    try:
        os.makedirs(os.path.dirname(NFA_GROUP_AUTH_FILE), exist_ok=True)
        with open(NFA_GROUP_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _nfa_group_authorized.items()}, f)
    except Exception as e:
        _log.warning(f"[授权] 保存群授权文件失败: {e}")


_nfa_group_authorized: dict[int, list[str]] = _load_nfa_group_authorized()


def _user_has_feature(user_id: int, feature: str) -> bool:
    """检查个人是否被授权了某功能"""
    perms = _nfa_user_authorized.get(user_id, [])
    return "all" in perms or feature in perms


def _group_has_feature(group_id: int, feature: str) -> bool:
    """检查群是否被授权了某功能"""
    perms = _nfa_group_authorized.get(group_id, [])
    return "all" in perms or feature in perms


def _fmt_perms(perms: list[str]) -> str:
    """格式化权限列表为可读字符串"""
    if "all" in perms:
        return "全部功能"
    return "、".join(perms)


# Ban 封禁系统（被封禁的用户无法使用任何Bot功能）
BANNED_USERS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "banned_users.json"
)


def _load_banned_users() -> set[int]:
    """从文件加载被封禁的用户列表"""
    try:
        if os.path.exists(BANNED_USERS_FILE):
            with open(BANNED_USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            banned = set(int(uid) for uid in data)
            if banned:
                _log.info(f"[BAN] 已加载 {len(banned)} 个封禁用户")
            return banned
    except Exception as e:
        _log.warning(f"[BAN] 加载封禁文件失败: {e}")
    return set()


def _save_banned_users():
    """保存封禁用户列表到文件"""
    try:
        os.makedirs(os.path.dirname(BANNED_USERS_FILE), exist_ok=True)
        with open(BANNED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_banned_users), f)
    except Exception as e:
        _log.warning(f"[BAN] 保存封禁文件失败: {e}")


_banned_users: set[int] = _load_banned_users()

# Staff 员工系统（需自设密码登陆，权限与admin类似但不能用/nfa和/addstaff）
STAFF_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "staff.json"
)


def _load_staff() -> dict[int, dict]:
    """从文件加载 staff 列表，格式: {qq_int: {"password": "xxx"}}"""
    try:
        if os.path.exists(STAFF_FILE):
            with open(STAFF_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            staff = {int(uid): info for uid, info in data.items()}
            if staff:
                _log.info(f"[STAFF] 已加载 {len(staff)} 个 Staff")
            return staff
    except Exception as e:
        _log.warning(f"[STAFF] 加载Staff文件失败: {e}")
    return {}


def _save_staff():
    """保存 staff 列表到文件"""
    try:
        os.makedirs(os.path.dirname(STAFF_FILE), exist_ok=True)
        with open(STAFF_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {str(uid): info for uid, info in _staff.items()}, f, ensure_ascii=False
            )
    except Exception as e:
        _log.warning(f"[STAFF] 保存Staff文件失败: {e}")


_staff: dict[int, dict] = _load_staff()

# staff 运行时已登陆状态（重启后清空，需重新 /auth 密码 登陆）
_staff_logged_in: set[int] = set()

# 交互式删除 staff 选择状态 {user_key: {"staff_list": [...], "expire": timestamp}}
_deletestaff_waiting: dict[str, dict] = {}

# 广告列表查看状态 {user_key: expire_timestamp}
_ad_waiting: dict[str, float] = {}
AD_WAIT_EXPIRE = 300

# 广告系统
ADS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ads.json")
_command_ads_enabled = contextvars.ContextVar("command_ads_enabled", default=False)


def _default_ads() -> list[dict]:
    return [
        {
            "id": 1,
            "content": "欢迎进入无限免费小号群喵：1097445697",
            "enabled": True,
            "active_until": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    ]


def _save_ads():
    try:
        os.makedirs(os.path.dirname(ADS_FILE), exist_ok=True)
        with open(ADS_FILE, "w", encoding="utf-8") as f:
            json.dump(_ads, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.warning(f"[广告] 保存广告文件失败: {e}")


def _load_ads() -> list[dict]:
    try:
        if os.path.exists(ADS_FILE):
            with open(ADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                normalized = []
                for item in data:
                    if not isinstance(item, dict) or not item.get("content"):
                        continue
                    normalized.append(
                        {
                            "id": int(item.get("id", len(normalized) + 1)),
                            "content": str(item.get("content", "")).strip(),
                            "enabled": bool(item.get("enabled", False)),
                            "active_until": item.get("active_until"),
                            "created_at": item.get(
                                "created_at",
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            ),
                        }
                    )
                if normalized:
                    return normalized
    except Exception as e:
        _log.warning(f"[广告] 加载广告文件失败: {e}")

    ads = _default_ads()
    try:
        os.makedirs(os.path.dirname(ADS_FILE), exist_ok=True)
    except Exception:
        pass
    return ads


_ads: list[dict] = _load_ads()
if not os.path.exists(ADS_FILE):
    _save_ads()


def _cleanup_expired_ads(save: bool = True):
    now_ts = _time_mod.time()
    changed = False
    for ad in _ads:
        active_until = ad.get("active_until")
        if (
            ad.get("enabled")
            and isinstance(active_until, (int, float))
            and active_until <= now_ts
        ):
            ad["enabled"] = False
            ad["active_until"] = None
            changed = True
    if changed and save:
        _save_ads()


def _parse_ad_duration(raw: str) -> int | None:
    token = raw.strip().lower()
    if not token:
        return None
    if token.isdigit():
        return int(token) * 60

    match = re.fullmatch(r"(\d+)(m|min|mins|分钟|h|hr|hrs|小时|d|day|days|天)", token)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)
    if unit in {"m", "min", "mins", "分钟"}:
        return value * 60
    if unit in {"h", "hr", "hrs", "小时"}:
        return value * 3600
    return value * 86400


def _split_ad_body_and_duration(raw: str) -> tuple[str, int | None]:
    text = raw.strip()
    if not text:
        return "", None
    parts = text.rsplit(None, 1)
    if len(parts) == 2:
        duration = _parse_ad_duration(parts[1])
        if duration is not None:
            return parts[0].strip(), duration
    return text, None


def _format_ad_deadline(ad: dict) -> str:
    active_until = ad.get("active_until")
    if not active_until:
        return "永久"
    if not isinstance(active_until, (int, float)):
        return "永久"
    remain = int(active_until - _time_mod.time())
    if remain <= 0:
        return "已到期"
    if remain >= 86400:
        return f"{remain // 86400}天后到期"
    if remain >= 3600:
        return f"{remain // 3600}小时后到期"
    if remain >= 60:
        return f"{remain // 60}分钟后到期"
    return f"{remain}秒后到期"


def _find_ad(selector: str) -> dict | None:
    key = selector.strip()
    if not key:
        return None
    if key.isdigit():
        target_id = int(key)
        for ad in _ads:
            if ad.get("id") == target_id:
                return ad
        return None

    for ad in _ads:
        if ad.get("content") == key:
            return ad

    matched = [ad for ad in _ads if key in ad.get("content", "")]
    if len(matched) == 1:
        return matched[0]
    return None


def _format_ads_list() -> str:
    _cleanup_expired_ads()
    lines = ["当前广告列表喵~", "━━━━━━━━━━━━━━"]
    if not _ads:
        lines.append("（暂无广告）")
    else:
        for ad in sorted(_ads, key=lambda x: x.get("id", 0)):
            status = "展示中" if ad.get("enabled") else "未展示"
            lines.append(
                f"[{ad.get('id')}] {status} / {_format_ad_deadline(ad)}\n{ad.get('content', '')}"
            )
    lines.append("━━━━━━━━━━━━━━")
    lines.append("用法：/ad+ 内容 — 新增广告到列表")
    lines.append("      /ad- 编号或内容 — 从列表删除广告")
    lines.append("      /ads+ 编号 [30m/2h/1d] — 开启展示（不填时间=永久）")
    lines.append("      /ads- 编号 — 移除展示（广告仍保留在列表）")
    lines.append("      使用 /ads+、/ads- 前请先输入 /ad 查看列表")
    return "\n".join(lines)


def _get_active_ads() -> list[str]:
    _cleanup_expired_ads()
    return [
        ad.get("content", "") for ad in _ads if ad.get("enabled") and ad.get("content")
    ]


def _decorate_command_text(text: str) -> str:
    if not _command_ads_enabled.get():
        return text
    active_ads = _get_active_ads()
    if not active_ads:
        return text
    ad_block = "\n".join(active_ads)
    if not text:
        return ad_block
    return f"{text}\n\n━━━ 广告 ━━━\n{ad_block}"


def _is_admin_or_staff(user_id: int) -> bool:
    """检查用户是否为 admin 或已登陆的 staff"""
    return user_id in _admin_authorized or user_id in _staff_logged_in


def _can_use_feature(
    user_id: int, message_type: str, group_id: int, feature: str
) -> bool:
    """检查用户是否可使用某功能：管理员(全功能)、个人授权或群授权"""
    if user_id in _admin_authorized:
        return True
    if _user_has_feature(user_id, feature):
        return True
    return message_type == "group" and _group_has_feature(group_id, feature)


# NFA 冷却：非 admin/staff 用户每 30 分钟只能获取一次
_nfa_cooldown: dict[int, float] = {}  # {user_id: 上次成功获取的时间戳}
NFA_COOLDOWN_SECONDS = 1800  # 30 分钟
# NFA 一小时内获取记录 + 偷卡封禁
_nfa_hour_log: dict[int, list[float]] = {}
_nfa_banned: dict[int, float] = {}
_NFA_HOUR_LIMIT = 5
_NFA_BAN_DURATION = 86400  # 24小时

# ====== 邮箱绑定 {qq_number: email} ======
EMAIL_CONFIG = config.get("email", {})
EMAIL_BIND_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "email_binds.json"
)


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


def _get_bound_email(user_id: int) -> str:
    return _email_binds.get(str(user_id), "").strip()


def _default_qq_email(user_id: int) -> str:
    return f"{user_id}@qq.com"


def _get_result_email(user_id: int) -> str:
    return _get_bound_email(user_id) or _default_qq_email(user_id)


def _mask_email_addr(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = f"{local[:2]}***{local[-1]}"
    return f"{masked_local}@{domain}"


async def _send_resource_email(
    user_id: int, subject: str, body: str
) -> tuple[bool, str, str]:
    to_addr = _get_result_email(user_id)
    ok, err = await _send_result_email(to_addr, subject, body)
    return ok, to_addr, err


# 防重复处理：记录最近处理过的消息ID（OrderedDict做LRU淘汰）
_processed_msgs: OrderedDict = OrderedDict()
MAX_PROCESSED = 200

# 群聊上下文缓存：仅记录群聊消息，AI被@时才读取（轻量缓存，不影响性能）
_group_chat_cache: OrderedDict = (
    OrderedDict()
)  # {group_id: list}  OrderedDict用于LRU淘汰
MAX_GROUP_CONTEXT = 30  # 每个群最多缓存最近30条消息
MAX_GROUP_CACHE_GROUPS = 50  # 最多缓存50个群的上下文

# 消息优先级队列（VIP 优先处理，设置上限防止内存溢出）
_msg_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=500)
_msg_counter = 0  # 用于保证同优先级消息的先后顺序

# B站解析去重：每个群的每个链接只解析一次  {group_id: {bili_id: timestamp}}
_bili_parsed: dict[int, dict[str, float]] = {}

# Hypixel 封禁统计定时播报  {group_id: asyncio.Task}
_hypban_tasks: dict[int, asyncio.Task] = {}
BILI_DEDUP_EXPIRE = 3600  # 去重过期时间：1小时后同一链接可再次解析

# 布吉岛定时播报订阅群 {group_id}  持久化到文件
BJD_SUB_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "bjd_sub.json"
)


def _load_bjd_sub() -> set[int]:
    try:
        if os.path.exists(BJD_SUB_FILE):
            with open(BJD_SUB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(int(gid) for gid in data)
    except Exception as e:
        _log.warning(f"[布吉岛] 加载订阅文件失败: {e}")
    return set()


def _save_bjd_sub():
    try:
        os.makedirs(os.path.dirname(BJD_SUB_FILE), exist_ok=True)
        with open(BJD_SUB_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_bjd_sub_groups), f)
    except Exception as e:
        _log.warning(f"[布吉岛] 保存订阅文件失败: {e}")


_bjd_sub_groups: set[int] = _load_bjd_sub()

# 重启相关
RESTART_FLAG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", ".restart_flag"
)
_restart_task: asyncio.Task | None = None


def _write_restart_flag(message_type: str, user_id: int, group_id: int):
    """写入重启标记文件，记录重启来源以便重启后通知"""
    try:
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "message_type": message_type,
                    "user_id": user_id,
                    "group_id": group_id,
                    "time": _time_mod.time(),
                },
                f,
            )
    except Exception as e:
        _log.warning(f"[Restart] 写入重启标记失败: {e}")


async def _send_raw(ws, message_type: str, user_id: int, group_id: int, text: str):
    """直接发送消息，不等待确认回执（用于重启前的最后一条消息）"""
    await onebot.send_raw(ws, message_type, user_id, group_id, text)


import subprocess as _subprocess


def _do_restart():
    """重启 bot：优先利用 restart.bat 的自动重启循环，否则用临时脚本拉起"""
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable  # 当前运行的 Python 路径（含 venv）

    # 写一个临时 bat：等旧进程退出后再启动新进程
    bat_path = os.path.join(bot_dir, "data", "_restart_tmp.bat")
    os.makedirs(os.path.dirname(bat_path), exist_ok=True)

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(f"@echo off\n")
        f.write(f"chcp 65001 >nul 2>&1\n")
        f.write(f"title QQ Bot (Restarting...)\n")
        f.write(f"timeout /t 2 /nobreak >nul\n")
        f.write(f'cd /d "{bot_dir}"\n')
        f.write(f"echo [Restart] Starting bot with: {python_exe}\n")
        f.write(f'"{python_exe}" bot.py\n')
        f.write(f"pause\n")
        f.write(f'del "%~f0"\n')

    _log.info(f"[Restart] 启动重启脚本, Python={python_exe}")
    _subprocess.Popen(
        ["cmd", "/c", bat_path],
        cwd=bot_dir,
        creationflags=_subprocess.CREATE_NEW_CONSOLE
        | _subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    _log.info("[Restart] 当前进程退出")
    os._exit(0)


async def _check_restart_flag(ws):
    """启动后检查重启标记，向触发者发送重启成功通知"""
    if not os.path.exists(RESTART_FLAG_FILE):
        return
    try:
        with open(RESTART_FLAG_FILE, "r", encoding="utf-8") as f:
            flag = json.load(f)
        os.remove(RESTART_FLAG_FILE)

        msg_type = flag.get("message_type", "private")
        uid = flag.get("user_id", 0)
        gid = flag.get("group_id", 0)
        old_time = flag.get("time", 0)
        elapsed = _time_mod.time() - old_time if old_time else 0

        # 等待 WS 连接稳定后再发送通知
        await asyncio.sleep(2)

        notify = f"✅ 机器人已重新启动。（耗时 {elapsed:.1f}s）"
        # 直接发送一次，不走重试机制（避免重复发送）
        await _send_raw(ws, msg_type, uid, gid, notify)
        _log.info(f"[Restart] 重启完成，已通知用户 {uid}")
    except Exception as e:
        _log.warning(f"[Restart] 读取重启标记失败: {e}")
        try:
            os.remove(RESTART_FLAG_FILE)
        except OSError:
            pass


def is_at_me(message) -> bool:
    return _is_at_me_impl(message, BOT_QQ)


def _extract_at_qq(raw_message) -> int | None:
    return _extract_at_qq_impl(raw_message, BOT_QQ)


def _is_ws_closed(ws) -> bool:
    return onebot.is_ws_closed(ws)


async def send_reply(
    ws, message_type: str, user_id: int, group_id: int, reply_text: str
):
    """统一发送回复"""
    await onebot.send_reply(
        ws, message_type, user_id, group_id, _decorate_command_text(reply_text)
    )


async def send_group_msg(ws, group_id: int, text: str):
    """发送群消息"""
    await onebot.send_group_msg(ws, group_id, _decorate_command_text(text))


async def send_private_msg(ws, user_id: int, text: str):
    """发送私聊消息"""
    await onebot.send_private_msg(ws, user_id, _decorate_command_text(text))


async def send_reply_plain(
    ws, message_type: str, user_id: int, group_id: int, reply_text: str
):
    token = _command_ads_enabled.set(False)
    try:
        await onebot.send_reply(ws, message_type, user_id, group_id, reply_text)
    finally:
        _command_ads_enabled.reset(token)


async def _execute_command(
    ws,
    content: str,
    message_type: str,
    user_id: int,
    group_id: int,
    nickname: str,
    raw_message="",
) -> bool:
    token = _command_ads_enabled.set(True)
    try:
        return await handle_command(
            ws, content, message_type, user_id, group_id, nickname, raw_message
        )
    finally:
        _command_ads_enabled.reset(token)


async def send_api_request(ws, action: str, params: dict, timeout: float = 10) -> dict:
    """发送 API 请求并等待响应"""
    return await onebot.send_api_request(ws, action, params, timeout=timeout)


def _extract_message_id(resp: dict) -> int | None:
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and data.get("message_id") is not None:
        return data.get("message_id")
    if isinstance(resp, dict) and resp.get("message_id") is not None:
        return resp.get("message_id")
    return None


async def _send_loading_message(
    ws, message_type: str, user_id: int, group_id: int, text: str
) -> int | None:
    action = "send_group_msg" if message_type == "group" else "send_private_msg"
    params = (
        {"group_id": group_id, "message": _decorate_command_text(text)}
        if message_type == "group"
        else {"user_id": user_id, "message": _decorate_command_text(text)}
    )
    resp = await send_api_request(ws, action, params, timeout=15)
    if resp.get("retcode") != 0:
        return None
    return _extract_message_id(resp)


async def _delete_message(ws, message_id: int | None):
    if message_id is None:
        return
    await send_api_request(ws, "delete_msg", {"message_id": message_id}, timeout=5)


async def _send_resource_result(
    ws,
    message_type: str,
    user_id: int,
    group_id: int,
    resource_key: str,
    resource_label: str,
    subject: str,
    result: str,
) -> bool:
    ok, to_addr, err = await _send_resource_email(user_id, subject, result)
    masked_addr = _mask_email_addr(to_addr)
    if ok:
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"{resource_label} 已发送到邮箱 {masked_addr}，请查收喵~",
        )
        return True

    _log.warning(f"[{resource_key}] 邮件发送失败 -> {masked_addr}: {err}")
    if message_type == "group":
        resp = await send_api_request(
            ws,
            "send_private_msg",
            {"user_id": user_id, "message": _decorate_command_text(result)},
        )
        if resp.get("retcode") == 0:
            await send_group_msg(
                ws,
                group_id,
                f"{resource_label} 邮件发送失败，已改为私发，请查看私聊喵~",
            )
        else:
            await send_group_msg(ws, group_id, f"[CQ:at,qq={user_id}] {result}")
    else:
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"{resource_label} 邮件发送失败，已改为当前会话发送喵~\n{result}",
        )
    return False


async def _handle_pending_command_hint(
    ws,
    message_type: str,
    user_id: int,
    group_id: int,
    user_key: str,
    content: str,
    nickname: str = "",
    raw_message: str = "",
) -> bool:
    hint = _command_hint_waiting.get(user_key)
    if not hint:
        return False

    if _time_mod.time() > hint.get("expire", 0):
        del _command_hint_waiting[user_key]
        return False

    lowered = content.strip().lower()
    if lowered == "y":
        del _command_hint_waiting[user_key]
        real_command = hint["original_input"]
        _log.info(f"[模糊指令] {nickname} 确认执行: {real_command}")
        # 直接执行真正的指令
        await _execute_command(
            ws, real_command, message_type, user_id, group_id, nickname, raw_message
        )
        return True

    if lowered in {"n", "no", "取消", "算了"}:
        del _command_hint_waiting[user_key]
        await send_reply(ws, message_type, user_id, group_id, "好的喵~已取消")
        return True

    if content.startswith("/"):
        del _command_hint_waiting[user_key]

    return False


async def _maybe_suggest_command(
    ws, message_type: str, user_id: int, group_id: int, user_key: str, content: str
) -> bool:
    if not content.startswith("/") or _is_known_slash_command(content):
        return False

    spec = _find_fuzzy_command(content)
    if not spec:
        return False

    # 构建真正要执行的指令：用正确的指令名替换输错的部分，保留参数
    wrong_token = _get_command_token(content)
    correct_cmd = spec["command"]
    if content.strip() == wrong_token:
        # 无参数，直接用正确指令
        original_input = correct_cmd
    else:
        # 有参数，替换指令名保留后面的参数
        original_input = correct_cmd + content[len(wrong_token) :]

    _command_hint_waiting[user_key] = {
        "command": correct_cmd,
        "original_input": original_input,
        "expire": _time_mod.time() + COMMAND_HINT_EXPIRE,
    }
    await send_reply(
        ws,
        message_type,
        user_id,
        group_id,
        f"你是不是想输入 {correct_cmd} 呀？\n回复 y 确认执行喵~",
    )
    return True


async def _handle_4399(ws, message_type, user_id, group_id, nickname, loading_msg_id=None):
    """后台任务：获取 sauth 并发送到邮箱，邮件失败时私聊/群聊兜底"""
    try:
        success, result = await sauth.get_sauth()
        _tail = "\n爱来自Miracle小号网站喵~"
        if not success:
            await send_reply(ws, message_type, user_id, group_id, result)
            return

        full_result = f"{result}{_tail}"
        await _delete_message(ws, loading_msg_id)
        email_ok = await _send_resource_result(
            ws,
            message_type,
            user_id,
            group_id,
            "4399",
            "4399 Sauth",
            "Miracle 4399 Sauth",
            full_result,
        )
        _log.info(f"[4399] {nickname}({'邮件' if email_ok else '兜底'})")
    except Exception as e:
        _log.error(f"[4399] 处理出错: {e}")
        await send_reply(
            ws, message_type, user_id, group_id, "获取 sauth 出错了喵，请稍后再试~"
        )


async def handle_command(
    ws,
    content: str,
    message_type: str,
    user_id: int,
    group_id: int,
    nickname: str,
    raw_message="",
) -> bool:
    """
    处理内置指令，返回 True 表示已处理
    """
    # 签到
    if content in ("签到", "打卡"):
        result = fun.do_sign(str(user_id), nickname)
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[签到] {nickname}")
        return True

    # Admin / Staff 授权验证
    if content == "/auth":
        if user_id in _staff:
            staff_info = _staff[user_id]
            if staff_info.get("password", "") == "":
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "您已被添加为 Staff 喵~请私聊曦曦发送 /auth 您的密码 来设置密码并激活权限！",
                )
            else:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "请私聊曦曦发送 /auth 您的密码 来登陆 Staff 账号喵~",
                )
        else:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "请输入验证码启用管理权限喵~格式：/auth 验证码",
            )
        return True

    if content.startswith("/auth ") or content.startswith("/auth:"):
        code = content.split(None, 1)[-1].lstrip(":").strip()

        # 1. Admin 验证：私聊 + 匹配 admin 验证码
        if message_type == "private" and code == ADMIN_AUTH_CODE:
            _admin_authorized.add(user_id)
            _save_admin_authorized()
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "✅ 登陆成功喵~您现在可以使用管理指令了！（/nfa、/shutdown 等）\n授权已持久化，重启后无需重新验证~",
            )
            _log.info(f"[AUTH] {nickname}({user_id}) Admin验证成功（已持久化）")
            return True

        # 2. Staff 验证：用户在 staff 列表中（私聊或群聊均可）
        if user_id in _staff:
            staff_info = _staff[user_id]
            if staff_info.get("password", "") == "":
                # 首次设密码激活
                _staff[user_id]["password"] = code
                _save_staff()
                _staff_logged_in.add(user_id)
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"✅ Staff 账号激活成功喵~已为您设置密码！\n您现在可以使用 Staff 管理指令了（/ban、/staff 等）\n每次Bot重启后请私聊 /auth 您的密码 重新登陆~",
                )
                _log.info(f"[AUTH] {nickname}({user_id}) Staff首次激活设密码")
                return True
            elif staff_info.get("password") == code:
                # 密码正确，登陆
                _staff_logged_in.add(user_id)
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "✅ Staff 登陆成功喵~您现在可以使用管理指令了！",
                )
                _log.info(f"[AUTH] {nickname}({user_id}) Staff登陆成功")
                return True
            else:
                # 密码错误
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "Staff 密码错误喵~请重新输入正确的密码",
                )
                _log.info(f"[AUTH] {nickname}({user_id}) Staff密码错误")
                return True

        # 3. 其他情况：验证失败
        await send_reply(
            ws, message_type, user_id, group_id, "验证码错误或请在私聊中验证喵~"
        )
        _log.info(f"[AUTH] {nickname}({user_id}) 验证失败")
        return True

    # Admin / Staff 退出授权
    if content in ("/quit", "quit"):
        if user_id in _admin_authorized:
            _admin_authorized.discard(user_id)
            _save_admin_authorized()
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "已退出管理员登陆喵~如需再次使用请重新验证",
            )
            _log.info(f"[QUIT] {nickname}({user_id}) 退出Admin授权")
        elif user_id in _staff_logged_in:
            _staff_logged_in.discard(user_id)
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "已退出 Staff 登陆喵~如需再次使用请重新 /auth 密码 登陆",
            )
            _log.info(f"[QUIT] {nickname}({user_id}) 退出Staff登陆")
        else:
            await send_reply(ws, message_type, user_id, group_id, "您当前没有登陆喵~")
        return True

    # Admin 后台面板（需要 /auth 登陆）
    if content in ("/admin", "admin"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要管理权限喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        admin_count = len(_admin_authorized)
        banned_count = len(_banned_users)
        staff_count = len(_staff)
        nfa_user_count = len(_nfa_user_authorized)
        nfa_group_count = len(_nfa_group_authorized)
        admin_list = (
            "\n".join(f"  · {uid}" for uid in sorted(_admin_authorized))
            if _admin_authorized
            else "  （暂无）"
        )
        banned_list = (
            "\n".join(f"  · {uid}" for uid in sorted(_banned_users))
            if _banned_users
            else "  （暂无）"
        )
        nfa_group_list = (
            "\n".join(
                f"  · {gid} [{_fmt_perms(perms)}]"
                for gid, perms in sorted(_nfa_group_authorized.items())
            )
            if _nfa_group_authorized
            else "  （暂无）"
        )
        nfa_user_list = (
            "\n".join(
                f"  · {uid} [{_fmt_perms(perms)}]"
                for uid, perms in sorted(_nfa_user_authorized.items())
            )
            if _nfa_user_authorized
            else "  （暂无）"
        )

        if _staff:
            staff_lines = []
            for qq in sorted(_staff.keys()):
                status = "✅已激活" if _staff[qq].get("password", "") else "⏳待激活"
                logged = " 🟢在线" if qq in _staff_logged_in else ""
                staff_lines.append(f"  · {qq} ({status}{logged})")
            staff_list_text = "\n".join(staff_lines)
        else:
            staff_list_text = "  （暂无）"

        msg = (
            f"🔧 曦曦管理后台\n"
            f"━━━━━━━━━━━━━━\n"
            f"👑 已授权管理员 ({admin_count}人)：\n"
            f"{admin_list}\n"
            f"\n"
            f"🛡️ Staff ({staff_count}人)：\n"
            f"{staff_list_text}\n"
            f"\n"
            f"🔓 NFA 个人授权 ({nfa_user_count}人)：\n"
            f"{nfa_user_list}\n"
            f"\n"
            f"🔑 NFA 群授权 ({nfa_group_count}个)：\n"
            f"{nfa_group_list}\n"
            f"\n"
            f"🚫 已封禁用户 ({banned_count}人)：\n"
            f"{banned_list}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📋 管理指令：\n"
            f"  /ban QQ号 — 封禁用户\n"
            f"  /unban QQ号 — 解封用户\n"
            f"  /staff — Staff管理面板\n"
            f"  /quit — 退出登陆"
        )
        # Admin 看到额外指令
        if user_id in _admin_authorized:
            msg += f"\n  /addstaff QQ号/@用户 — 添加Staff\n  /deletestaff — 移除Staff\n  /授权 — 查看授权指令用法\n  /授权q QQ号 功能 — 个人授权\n  /授权群 群号 功能 — 群授权\n  /取消授权 群号/QQ号 — 取消授权\n  /ad — 广告管理"
        await send_reply(ws, message_type, user_id, group_id, msg)
        _log.info(f"[ADMIN] {nickname}({user_id}) 查看管理后台")
        return True

    # ═══ 授权指令帮助 ═══
    if content == "/授权":
        if user_id not in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令仅限管理员使用喵~",
            )
            return True
        help_text = (
            "📋 授权指令用法\n"
            "━━━━━━━━━━━━━━\n"
            "个人授权：\n"
            "  /授权q QQ号 all — 全部功能\n"
            "  /授权q QQ号 nfa — 仅 NFA\n"
            "  /授权q QQ号 4399 — 仅 4399\n"
            "  /授权q QQ号 163 — 仅 163\n"
            "\n"
            "群授权：\n"
            "  /授权群 群号 all — 全部功能\n"
            "  /授权群 群号 nfa — 仅 NFA\n"
            "  /授权群 群号 4399 — 仅 4399\n"
            "  /授权群 群号 163 — 仅 163\n"
            "\n"
            "取消授权：\n"
            "  /取消授权 群号/QQ号\n"
            "━━━━━━━━━━━━━━\n"
            "可用功能：all | nfa | 4399 | 163\n"
            "不指定功能时默认为 all"
        )
        await send_reply(ws, message_type, user_id, group_id, help_text)
        return True

    # ═══ 个人授权（仅 Admin）═══
    if content.startswith("/授权q ") or content.startswith("/授权q:"):
        if user_id not in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令仅限管理员使用喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        parts = content.split(None)
        target_str = parts[1].lstrip(":：") if len(parts) > 1 else ""
        qq_match = re.search(r"(\d{5,12})", target_str)
        if not qq_match:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "格式错误喵~用法：/授权q QQ号 [功能]\n功能可选：all | nfa | 4399 | 163（默认 all）",
            )
            return True

        target_qq = int(qq_match.group(1))
        feature = parts[2].strip().lower() if len(parts) > 2 else "all"

        if feature != "all" and feature not in ALL_FEATURES:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"未知功能 '{feature}' 喵~可选：all | nfa | 4399 | 163",
            )
            return True

        if target_qq in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 本来就是管理员喵~无需额外授权",
            )
            return True

        current = _nfa_user_authorized.get(target_qq, [])
        if "all" in current:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 已拥有全部功能授权喵~",
            )
            return True
        if feature != "all" and feature in current:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 已拥有 {feature} 权限喵~",
            )
            return True

        if feature == "all":
            _nfa_user_authorized[target_qq] = ["all"]
        else:
            new_perms = list(current) + [feature]
            _nfa_user_authorized[target_qq] = new_perms
        _save_nfa_user_authorized()

        feat_desc = "全部功能" if feature == "all" else feature
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"✅ 授权成功喵~\nQQ {target_qq} 已获得 [{feat_desc}] 权限",
        )
        _log.info(f"[授权] {nickname}({user_id}) 授权个人 {target_qq} → {feature}")
        return True

    # ═══ 群授权（仅 Admin）═══
    if content.startswith("/授权群 ") or content.startswith("/授权群:"):
        if user_id not in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令仅限管理员使用喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        parts = content.split(None)
        target_str = parts[1].lstrip(":：") if len(parts) > 1 else ""
        group_match = re.search(r"(\d{5,12})", target_str)
        if not group_match:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "格式错误喵~用法：/授权群 群号 [功能]\n功能可选：all | nfa | 4399 | 163（默认 all）",
            )
            return True

        target_group = int(group_match.group(1))
        feature = parts[2].strip().lower() if len(parts) > 2 else "all"

        if feature != "all" and feature not in ALL_FEATURES:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"未知功能 '{feature}' 喵~可选：all | nfa | 4399 | 163",
            )
            return True

        current = _nfa_group_authorized.get(target_group, [])
        if "all" in current:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"群 {target_group} 已拥有全部功能授权喵~",
            )
            return True
        if feature != "all" and feature in current:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"群 {target_group} 已拥有 {feature} 权限喵~",
            )
            return True

        if feature == "all":
            _nfa_group_authorized[target_group] = ["all"]
        else:
            new_perms = list(current) + [feature]
            _nfa_group_authorized[target_group] = new_perms
        _save_nfa_group_authorized()

        feat_desc = "全部功能" if feature == "all" else feature
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"✅ 授权成功喵~\n群 {target_group} 已获得 [{feat_desc}] 权限",
        )
        _log.info(f"[授权] {nickname}({user_id}) 授权群 {target_group} → {feature}")
        return True

    # ═══ 取消授权（仅 Admin）═══
    if content.startswith("/取消授权 ") or content.startswith("/取消授权:"):
        if user_id not in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令仅限管理员使用喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        target = content.split(None, 1)[-1].lstrip(":：").strip()
        id_match = re.search(r"(\d{5,12})", target)
        if not id_match:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "格式错误喵~用法：/取消授权 群号或QQ号",
            )
            return True

        target_id = int(id_match.group(1))
        removed_from = []

        if target_id in _nfa_group_authorized:
            del _nfa_group_authorized[target_id]
            _save_nfa_group_authorized()
            removed_from.append("群授权")

        if target_id in _nfa_user_authorized:
            del _nfa_user_authorized[target_id]
            _save_nfa_user_authorized()
            removed_from.append("个人授权")

        if removed_from:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已取消 {target_id} 的{'、'.join(removed_from)}喵~",
            )
            _log.info(f"[授权] {nickname}({user_id}) 取消授权 {target_id}")
        else:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"{target_id} 当前没有任何授权喵~",
            )
        return True

    # Ban 封禁用户（需要 Admin 或 Staff 权限）
    if content.startswith("/ban ") or content.startswith("/ban:"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要管理权限喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        target = content.split(None, 1)[-1].lstrip(":").strip()
        # 提取QQ号
        qq_match = re.search(r"(\d{5,12})", target)
        if not qq_match:
            await send_reply(
                ws, message_type, user_id, group_id, "格式错误喵~用法：/ban QQ号"
            )
            return True

        target_qq = int(qq_match.group(1))

        if target_qq == user_id:
            await send_reply(ws, message_type, user_id, group_id, "不能封禁自己喵~")
            return True

        if target_qq in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 是管理员，无法封禁喵~请先让对方 /quit 退出管理员后再封禁",
            )
            return True

        if target_qq in _banned_users:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 已经在封禁列表中了喵~",
            )
            return True

        _banned_users.add(target_qq)
        _save_banned_users()
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"✅ 已封禁 QQ {target_qq}，该用户将无法使用曦曦的任何功能喵~",
        )
        _log.info(f"[BAN] {nickname}({user_id}) 封禁了 {target_qq}")
        return True

    # Unban 解封用户（需要 Admin 或 Staff 权限）
    if content.startswith("/unban ") or content.startswith("/unban:"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要管理权限喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        target = content.split(None, 1)[-1].lstrip(":").strip()
        qq_match = re.search(r"(\d{5,12})", target)
        if not qq_match:
            await send_reply(
                ws, message_type, user_id, group_id, "格式错误喵~用法：/unban QQ号"
            )
            return True

        target_qq = int(qq_match.group(1))

        if target_qq not in _banned_users:
            await send_reply(
                ws, message_type, user_id, group_id, f"QQ {target_qq} 不在封禁列表中喵~"
            )
            return True

        _banned_users.discard(target_qq)
        _save_banned_users()
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"✅ 已解封 QQ {target_qq}，该用户现在可以正常使用曦曦了喵~",
        )
        _log.info(f"[UNBAN] {nickname}({user_id}) 解封了 {target_qq}")
        return True

    # ===== Staff 管理指令 =====

    # /addstaff（仅 admin 可用，staff 不可）
    if content.startswith("/addstaff") or content.startswith("/add "):
        if user_id not in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要 Admin 权限喵~Staff 无法使用此指令",
            )
            return True

        # 从 raw_message 或 content 中提取目标QQ号
        target_qq = _extract_at_qq(raw_message)
        if not target_qq:
            param = content.split(None, 1)[-1].strip() if " " in content else ""
            qq_match = re.search(r"(\d{5,12})", param)
            if qq_match:
                target_qq = int(qq_match.group(1))

        if not target_qq:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "格式错误喵~用法：/addstaff QQ号 或 /addstaff @用户",
            )
            return True

        if target_qq == user_id:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "不需要把自己添加为 Staff 喵~您已经是 Admin 了！",
            )
            return True

        if target_qq in _admin_authorized:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 已经是 Admin，不需要再添加为 Staff 喵~",
            )
            return True

        if target_qq in _staff:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"QQ {target_qq} 已经是 Staff 了喵~",
            )
            return True

        # 添加到 staff 列表（密码为空表示未激活）
        _staff[target_qq] = {"password": ""}
        _save_staff()

        # 通知目标用户
        notify_msg = f"🎉 恭喜！您已被管理员 {nickname} 添加为曦曦 Staff 喵~\n请私聊曦曦发送 /auth 您的密码 来设置账号密码并激活权限！\n（密码由您自己设定，请牢记哦~）"
        if message_type == "private":
            # 私聊场景：直接私聊通知目标用户
            await send_api_request(
                ws, "send_private_msg", {"user_id": target_qq, "message": notify_msg}
            )
        else:
            # 群聊场景：在群里 @ 提醒
            await send_group_msg(ws, group_id, f"[CQ:at,qq={target_qq}] {notify_msg}")

        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"✅ 已将 QQ {target_qq} 添加为 Staff 喵~已通知对方去私聊设置密码激活！",
        )
        _log.info(f"[STAFF] {nickname}({user_id}) 添加了 Staff: {target_qq}")
        return True

    # /deletestaff（仅 admin 可用）
    if content == "/deletestaff" or content == "deletestaff":
        if user_id not in _admin_authorized:
            await send_reply(
                ws, message_type, user_id, group_id, "该指令需要 Admin 权限喵~"
            )
            return True

        if not _staff:
            await send_reply(
                ws, message_type, user_id, group_id, "当前没有任何 Staff 喵~"
            )
            return True

        # 列出 staff 列表，进入交互选择模式
        user_key = f"{message_type}_{group_id}_{user_id}"
        staff_list = sorted(_staff.keys())
        lines = ["📋 请选择要移除的 Staff：", "━━━━━━━━━━━━━━"]
        for i, qq in enumerate(staff_list, 1):
            status = "✅已激活" if _staff[qq].get("password", "") else "⏳待激活"
            logged = " 🟢在线" if qq in _staff_logged_in else ""
            lines.append(f"{i}. QQ {qq} ({status}{logged})")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("回复序号删除，回复「取消」可取消操作")

        _deletestaff_waiting[user_key] = {
            "staff_list": staff_list,
            "expire": _time_mod.time() + 60,
        }
        await send_reply(ws, message_type, user_id, group_id, "\n".join(lines))
        _log.info(f"[STAFF] {nickname}({user_id}) 进入交互式删除Staff模式")
        return True

    if content.startswith("/deletestaff ") or content.startswith("/deletestaff:"):
        if user_id not in _admin_authorized:
            await send_reply(
                ws, message_type, user_id, group_id, "该指令需要 Admin 权限喵~"
            )
            return True

        # 从 @用户 或 QQ号 提取
        target_qq = _extract_at_qq(raw_message)
        if not target_qq:
            param = content.split(None, 1)[-1].lstrip(":").strip()
            qq_match = re.search(r"(\d{5,12})", param)
            if qq_match:
                target_qq = int(qq_match.group(1))

        if not target_qq:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "格式错误喵~用法：/deletestaff QQ号 或 /deletestaff @用户",
            )
            return True

        if target_qq not in _staff:
            await send_reply(
                ws, message_type, user_id, group_id, f"QQ {target_qq} 不是 Staff 喵~"
            )
            return True

        del _staff[target_qq]
        _save_staff()
        _staff_logged_in.discard(target_qq)
        await send_reply(
            ws, message_type, user_id, group_id, f"✅ 已移除 Staff QQ {target_qq} 喵~"
        )
        _log.info(f"[STAFF] {nickname}({user_id}) 移除了 Staff: {target_qq}")
        return True

    # /staff 面板
    if content in ("/staff", "staff"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws, message_type, user_id, group_id, "该指令需要 Staff 或 Admin 权限喵~"
            )
            return True

        staff_count = len(_staff)
        banned_count = len(_banned_users)

        if _staff:
            staff_lines = []
            for qq in sorted(_staff.keys()):
                status = "✅已激活" if _staff[qq].get("password", "") else "⏳待激活"
                logged = " 🟢在线" if qq in _staff_logged_in else ""
                staff_lines.append(f"  · {qq} ({status}{logged})")
            staff_list_text = "\n".join(staff_lines)
        else:
            staff_list_text = "  （暂无）"

        banned_list = (
            "\n".join(f"  · {uid}" for uid in sorted(_banned_users))
            if _banned_users
            else "  （暂无）"
        )

        msg = (
            f"👥 曦曦 Staff 管理面板\n"
            f"━━━━━━━━━━━━━━\n"
            f"🛡️ Staff 列表 ({staff_count}人)：\n"
            f"{staff_list_text}\n"
            f"\n"
            f"🚫 已封禁用户 ({banned_count}人)：\n"
            f"{banned_list}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📋 可用指令：\n"
            f"  /ban QQ号 — 封禁用户\n"
            f"  /unban QQ号 — 解封用户\n"
            f"  /quit — 退出登陆"
        )
        # Admin 看到额外指令
        if user_id in _admin_authorized:
            msg += f"\n  /addstaff QQ号/@用户 — 添加Staff\n  /deletestaff — 移除Staff\n  /授权 — 查看授权指令用法\n  /授权q QQ号 功能 — 个人授权\n  /授权群 群号 功能 — 群授权\n  /取消授权 群号/QQ号 — 取消授权\n  /ad — 广告管理"

        await send_reply(ws, message_type, user_id, group_id, msg)
        _log.info(f"[STAFF] {nickname}({user_id}) 查看Staff面板")
        return True

    # 广告管理（需要 Admin 或 Staff 权限）
    _ad_match = re.match(r"^/ad(s?\+|s?-|)\s*(.*)", content or "", re.DOTALL)
    if _ad_match:
        _log.info(
            f"[广告] 进入 /ad 分支: content={content!r} user={user_id} admin={user_id in _admin_authorized}"
        )
        if user_id not in _admin_authorized:
            await send_reply_plain(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令仅限 Admin 使用喵~Staff 无权操作广告",
            )
            return True

        ad_user_key = f"{message_type}_{group_id}_{user_id}"
        ad_wait_until = _ad_waiting.get(ad_user_key, 0)
        if ad_wait_until and ad_wait_until <= _time_mod.time():
            _ad_waiting.pop(ad_user_key, None)
            ad_wait_until = 0

        action = _ad_match.group(1)
        payload = _ad_match.group(2).strip()

        if not action:
            _ad_waiting[ad_user_key] = _time_mod.time() + AD_WAIT_EXPIRE
            await send_reply_plain(
                ws, message_type, user_id, group_id, _format_ads_list()
            )
            _log.info(f"[广告] {nickname}({user_id}) 查看广告列表")
            return True

        if action == "+":
            if not payload:
                await send_reply_plain(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "格式错误喵~用法：/ad+ 广告内容",
                )
                return True
            new_id = max((int(ad.get("id", 0)) for ad in _ads), default=0) + 1
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
            await send_reply_plain(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已新增广告 [{new_id}] 到列表喵~（未展示）\n使用 /ads+ {new_id} 开启展示\n\n{_format_ads_list()}",
            )
            _log.info(f"[广告] {nickname}({user_id}) 新增广告 [{new_id}]")
            return True

        if action == "-":
            ad = _find_ad(payload)
            if not ad:
                await send_reply_plain(
                    ws, message_type, user_id, group_id, "没有找到这个广告喵~"
                )
                return True
            _ads.remove(ad)
            _save_ads()
            await send_reply_plain(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已从列表删除广告 [{ad.get('id')}] 喵~\n\n{_format_ads_list()}",
            )
            _log.info(f"[广告] {nickname}({user_id}) 删除广告 [{ad.get('id')}]")
            return True

        if action == "s+":
            if ad_wait_until <= 0:
                await send_reply_plain(
                    ws, message_type, user_id, group_id, "请先输入/ad 查看列表"
                )
                return True
            selector, duration = _split_ad_body_and_duration(payload)
            ad = _find_ad(selector)
            if not ad:
                await send_reply_plain(
                    ws, message_type, user_id, group_id, "没有找到这个广告喵~"
                )
                return True
            ad["enabled"] = True
            ad["active_until"] = _time_mod.time() + duration if duration else None
            _save_ads()
            duration_text = f"（{_format_ad_deadline(ad)}）" if duration else "（永久）"
            await send_reply_plain(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已开始展示广告 [{ad.get('id')}] {duration_text} 喵~\n\n{_format_ads_list()}",
            )
            _log.info(f"[广告] {nickname}({user_id}) 启用广告 [{ad.get('id')}]")
            return True

        if action == "s-":
            if ad_wait_until <= 0:
                await send_reply_plain(
                    ws, message_type, user_id, group_id, "请先输入/ad 查看列表"
                )
                return True
            ad = _find_ad(payload)
            if not ad:
                await send_reply_plain(
                    ws, message_type, user_id, group_id, "没有找到这个广告喵~"
                )
                return True
            ad["enabled"] = False
            ad["active_until"] = None
            _save_ads()
            await send_reply_plain(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已移除展示广告 [{ad.get('id')}] 喵~（广告仍在列表中）\n\n{_format_ads_list()}",
            )
            _log.info(f"[广告] {nickname}({user_id}) 停用广告 [{ad.get('id')}]")
            return True

        return True

    # ===== 绑定邮箱 =====
    bind_match = re.match(r"^(?:/bind|/绑定邮箱)\s+(\S+@\S+\.\S+)$", content or "", re.IGNORECASE)
    if bind_match:
        email = _normalize_email_addr(bind_match.group(1))
        if not _is_valid_email_addr(email):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "邮箱格式不对喵~请输入：/bind 你的邮箱地址\n例如：/bind 123456@qq.com",
            )
            return True
        _email_binds[str(user_id)] = email
        _save_email_binds()
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"邮箱绑定成功喵~\n{email}\n之后领取 nfa/4399/163 会自动发到这个邮箱！",
        )
        _log.info(f"[邮箱] {nickname}({user_id}) 绑定 {email}")
        return True

    if content in ("/bind", "bind", "/绑定邮箱", "绑定邮箱") or re.match(
        r"^(?:/bind|/绑定邮箱)\s+", content or "", re.IGNORECASE
    ):
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            "请输入：/bind 你的邮箱地址\n例如：/bind 123456@qq.com\n不绑定时默认发送到你的 QQ 邮箱，也可以随时重新绑定喵~",
        )
        return True

    if content in ("/解绑邮箱", "解绑邮箱", "/unbind", "unbind"):
        if str(user_id) in _email_binds:
            del _email_binds[str(user_id)]
            _save_email_binds()
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "已解绑邮箱喵~之后会默认发送到你的 QQ 邮箱。",
            )
        else:
            await send_reply(ws, message_type, user_id, group_id, "你还没有绑定邮箱喵~")
        return True

    # NFA 获取（需要先通过 /auth 验证）
    if content in ("/nfa", "nfa"):
        if not _can_use_feature(user_id, message_type, group_id, "nfa"):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "您当前没有该权限喵~请先私聊曦曦发送 /auth 验证码，或让管理员使用 /授权q QQ号 /授权群 群号 开通权限",
            )
            _log.info(f"[NFA] {nickname}({user_id}) 未授权")
            return True

        # 非 admin/staff 用户：跨 bot 共享冷却 + 频率 + 封禁
        if not _is_admin_or_staff(user_id):
            banned, bh, bm = _shared_cd.is_banned("nfa", user_id)
            if banned:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~",
                )
                return True

            in_cd, cd_remain = _shared_cd.check_cooldown(
                "nfa", user_id, NFA_COOLDOWN_SECONDS
            )
            if in_cd:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"获取太频繁啦喵~请 {cd_remain // 60}分{cd_remain % 60}秒 后再试~",
                )
                _log.info(f"[NFA] {nickname}({user_id}) 冷却中，剩余{cd_remain}秒")
                return True

            over_limit, count = _shared_cd.check_hour_limit(
                "nfa", user_id, _NFA_HOUR_LIMIT, _NFA_BAN_DURATION
            )
            if over_limit:
                _log.warning(
                    f"[NFA] {nickname}({user_id}) 疑似偷卡，一小时内获取{count}次，封禁24h"
                )
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"您在一小时内频繁获取NFA（{count}次），疑似偷卡行为，已被临时封禁24小时喵~",
                )
                return True

            _shared_cd.record_usage("nfa", user_id)

        result = await nfa.get_nfa_token("admin", "zutomayo0.")
        if "主人您的nfa来了喵" in result:
            result += "\n爱来自Miracle nfa bot喵~"
            await _send_resource_result(
                ws,
                message_type,
                user_id,
                group_id,
                "NFA",
                "NFA",
                "Miracle NFA Token",
                result,
            )
        else:
            await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[NFA] {nickname}({user_id}) group={group_id}")
        return True

    # 库存总览
    if content in ("/stock", "stock"):
        lines = ["Miracle Bot 库存总览喵~", "━━━━━━━━━━━━━━"]

        # NFA 库存（API）
        try:
            nfa_ok, nfa_count, _ = await nfa.get_nfa_stock()
            lines.append(f"NFA：{nfa_count}" if nfa_ok else "NFA：unavailable")
        except Exception:
            lines.append("NFA：unavailable")

        # 4399 库存（API）
        try:
            ok_4399, avail_4399, total_4399, _ = await sauth.get_4399_stock()
            lines.append(
                f"4399：{avail_4399}/{total_4399}" if ok_4399 else "4399：unavailable"
            )
        except Exception:
            lines.append("4399：unavailable")

        # 163 库存（本地文件）
        try:
            accounts_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "data", "163accounts.txt"
            )
            with open(accounts_file, "r", encoding="utf-8") as f:
                count_163 = sum(
                    1
                    for line in f
                    if line.strip()
                    and not line.strip().startswith("#")
                    and "----" in line
                )
            lines.append(f"163：{count_163}")
        except Exception:
            lines.append("163：unavailable")

        lines.append("━━━━━━━━━━━━━━")
        await send_reply(ws, message_type, user_id, group_id, "\n".join(lines))
        _log.info(f"[库存] {nickname}({user_id}) 查询库存")
        return True

    # 163 小号领取（每人每分钟限领1个 + 一小时内超5次封禁24h，跨 bot 共享）
    if content in ("/163", "163"):
        if not _can_use_feature(user_id, message_type, group_id, "163"):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "您当前没有 163 权限喵~请让管理员使用 /授权q QQ号 163 或 /授权群 群号 163 开通权限",
            )
            return True

        banned, bh, bm = _shared_cd.is_banned("163", user_id)
        if banned:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"您因疑似偷卡已被临时封禁，剩余 {bh}小时{bm}分钟 后解封喵~",
            )
            return True

        in_cd, cd_remain = _shared_cd.check_cooldown("163", user_id, 60)
        if in_cd:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"您在一分钟之内已经获取过啦，请{cd_remain}秒后再获取喵~",
            )
            return True

        over_limit, count = _shared_cd.check_hour_limit(
            "163", user_id, _163_HOUR_LIMIT, _163_BAN_DURATION
        )
        if over_limit:
            _log.warning(
                f"[163] {nickname}({user_id}) 疑似偷卡，一小时内获取{count}次，封禁24h"
            )
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"您在一小时内频繁获取小号（{count}次），疑似偷卡行为，已被临时封禁24小时喵~",
            )
            return True

        _shared_cd.record_usage("163", user_id)
        accounts_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "163accounts.txt"
        )
        try:
            with open(accounts_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # 过滤出有效账号行（跳过注释和空行）
            valid_lines = []
            other_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "----" in stripped:
                    valid_lines.append(line)
                else:
                    other_lines.append(line)

            if not valid_lines:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "163小号暂时没有库存了喵~请稍后再试哦",
                )
                _log.info(f"[163] {nickname}({user_id}) 无库存")
                return True

            # 取第一个账号
            account_line = valid_lines[0].strip()
            parts = account_line.split("----", 1)
            account = parts[0].strip()
            password = parts[1].strip() if len(parts) > 1 else "未知"

            # 从文件中移除已领取的账号
            remaining = other_lines + valid_lines[1:]
            with open(accounts_file, "w", encoding="utf-8") as f:
                f.writelines(remaining)

            result = (
                f"主人您的163小号来了喵~\n"
                f"━━━━━━━━━━━━━━\n"
                f"账号：{account}\n"
                f"密码：{password}\n"
                f"━━━━━━━━━━━━━━\n"
                f"可能需要手机验证，需要主人自己过验证哦~\n"
                f"爱来自Miracle小号网~"
            )

            email_ok = await _send_resource_result(
                ws,
                message_type,
                user_id,
                group_id,
                "163",
                "163 小号",
                "Miracle 163 小号",
                result,
            )
            _log.info(f"[163] {nickname}({user_id}) {'邮件发送' if email_ok else '兜底发送'}")

            stock_left = len(valid_lines) - 1
            _log.info(f"[163] 剩余库存: {stock_left}")

        except FileNotFoundError:
            await send_reply(
                ws, message_type, user_id, group_id, "163小号文件不存在喵~请联系管理员"
            )
        except Exception as e:
            _log.error(f"[163] 获取失败: {e}")
            await send_reply(
                ws, message_type, user_id, group_id, "163小号获取出错了喵~请稍后再试"
            )
        return True

    # 4399 sauth 获取
    if content in ("/4399", "4399"):
        if not _can_use_feature(user_id, message_type, group_id, "4399"):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "您当前没有 4399 权限喵~请让管理员使用 /授权q QQ号 4399 或 /授权群 群号 4399 开通权限",
            )
            return True
        # 先回复提示
        loading_msg_id = await _send_loading_message(
            ws, message_type, user_id, group_id, "正在获取中，请稍后..."
        )
        # 用后台任务处理，避免阻塞 WebSocket 主循环
        asyncio.create_task(
            _handle_4399(ws, message_type, user_id, group_id, nickname, loading_msg_id)
        )
        return True

    # 排行榜
    if content in ("排行榜", "积分榜", "签到排行"):
        result = fun.get_ranking()
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[排行榜]")
        return True

    # 布吉岛版本查询
    if content in ("/bjd", "bjd", "布吉岛", "布吉岛版本"):
        info = await bjd.get_latest_version()
        if info:
            result = bjd.build_update_msg(info, is_update=False)
        else:
            result = "获取布吉岛版本信息失败喵~"
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[布吉岛] 手动查询")
        return True

    # 布吉岛定时播报 - 开启（仅群聊）
    if content in ("/bjdon", "bjdon"):
        if message_type != "group":
            await send_reply(
                ws, message_type, user_id, group_id, "定时播报仅支持群聊喵~"
            )
            return True
        if group_id in _bjd_sub_groups:
            await send_reply(
                ws, message_type, user_id, group_id, "本群已经开启了布吉岛定时播报喵~"
            )
            return True
        _bjd_sub_groups.add(group_id)
        _save_bjd_sub()
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            "已开启布吉岛定时播报（每天 12:00 和 18:00）喵~\n发送 /bjdoff 可关闭",
        )
        _log.info(f"[布吉岛] 群{group_id} 开启定时播报")
        return True

    # 布吉岛定时播报 - 关闭
    if content in ("/bjdoff", "bjdoff"):
        if message_type != "group":
            await send_reply(
                ws, message_type, user_id, group_id, "定时播报仅支持群聊喵~"
            )
            return True
        if group_id not in _bjd_sub_groups:
            await send_reply(
                ws, message_type, user_id, group_id, "本群没有开启布吉岛定时播报喵~"
            )
            return True
        _bjd_sub_groups.discard(group_id)
        _save_bjd_sub()
        await send_reply(ws, message_type, user_id, group_id, "已关闭布吉岛定时播报喵~")
        _log.info(f"[布吉岛] 群{group_id} 关闭定时播报")
        return True

    # Hypixel 封禁统计查询
    if content in ("/hypban", "hypban"):
        result = await hypban.get_ban_stats()
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[Hypixel] 封禁统计查询")
        return True

    # Hypixel 封禁统计 - 开启每分钟自动播报（仅群聊）
    if content in ("/hypban on", "hypban on"):
        if message_type != "group":
            await send_reply(
                ws, message_type, user_id, group_id, "自动播报仅支持群聊喵~"
            )
            return True
        if group_id in _hypban_tasks and not _hypban_tasks[group_id].done():
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "本群已经开启了 Hypixel 封禁自动播报喵~",
            )
            return True
        task = asyncio.create_task(_hypban_auto_loop(ws, group_id))
        _hypban_tasks[group_id] = task
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            "已开启 Hypixel 封禁统计自动播报（每分钟）喵~\n发送 /hypban off 可关闭",
        )
        _log.info(f"[Hypixel] 群{group_id} 开启自动播报")
        return True

    # Hypixel 封禁统计 - 关闭自动播报
    if content in ("/hypban off", "hypban off"):
        if message_type != "group":
            await send_reply(
                ws, message_type, user_id, group_id, "自动播报仅支持群聊喵~"
            )
            return True
        task = _hypban_tasks.pop(group_id, None)
        if task and not task.done():
            task.cancel()
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "已关闭 Hypixel 封禁统计自动播报喵~",
            )
            _log.info(f"[Hypixel] 群{group_id} 关闭自动播报")
        else:
            await send_reply(
                ws, message_type, user_id, group_id, "本群没有开启自动播报喵~"
            )
        return True

    # 完整更新日志
    if content in ("/datalog", "datalog", "更新日志"):
        changelog = (
            f"曦曦 Bot 完整更新日志\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"v{BOT_VERSION} ({BOT_BUILD_DATE})\n"
            f"· 新增邮件发送：nfa/4399/163 结果自动发到邮箱\n"
            f"· 新增 /bind 邮箱 /unbind 指令\n"
            f"· 未绑定邮箱时默认发送到 QQ 邮箱\n"
            f"· 邮件模板升级为 HTML 格式\n"
            f"· AI 模型切换为 gemini-3-flash-preview\n"
            f"\n"
            f"v3.1.2 (2026-04-06)\n"
            f"· 新增 /ad 广告管理：增删广告、启停展示、支持定时\n"
            f"· /ads+ 与 /ads- 需要先输入 /ad 查看列表后再操作\n"
            f"· 所有指令回复统一支持广告位（AI 对话除外）\n"
            f"· 4399 小号群改为默认广告，不再写死在单个指令里\n"
            f"\n"
            f"v3.2.0 (2026-04-12)\n"
            f"· 授权系统重构：/新增q → /授权q、/新增群 → /授权群\n"
            f"· 支持按功能授权：/授权q QQ号 all|nfa|4399|163\n"
            f"· 支持按功能授权：/授权群 群号 all|nfa|4399|163\n"
            f"· /取消授权 现同时支持群号和QQ号\n"
            f"· 新增 /授权 指令帮助页\n"
            f"· /4399、/163 新增权限检查（需授权后使用）\n"
            f"· /admin 面板显示每个授权对象的具体权限\n"
            f"· 旧授权数据启动时自动迁移，无需手动处理\n"
            f"· NFA 非管理员用户增加 10 分钟冷却限制\n"
            f"· NFA 登录错误信息修复（显示真实原因而非'未知错误'）\n"
            f"· Hypixel 封禁追踪 API 切换至 bantracker-api.xcnya.cn\n"
            f"· 新增 4399 库存查询（/stock 显示可用/总量）\n"
            f"· /restart 改为 /shutdown（仅本Bot）\n"
            f"\n"
            f"v3.1.1 (2026-04-06)\n"
            f"· 4399 sauth 新接口适配：增加 X-Api-Key 鉴权\n"
            f"· 4399 返回格式改为账号/密码/sauth 三行输出\n"
            f"\n"
            f"v3.1.0 (2026-04-04)\n"
            f"· 新增 /stock：查看 NFA/4399/163 全部库存\n"
            f"· 新增 /163：领取 163 小号\n"
            f"· 模糊指令识别：输错命令回复 y 直接执行正确指令\n"
            f"· 管理员私聊 Q qq号 / 群 群号 加好友或申请入群\n"
            f"· 网页链接自动截图：发送链接后先发网页截图再 AI 分析\n"
            f"· 消息缓存满 300 条自动导出 txt，撤回时自动回顾历史文件\n"
            f"\n"
            f"v3.0.4 (2026-04-02)\n"
            f"· AI 对话已切换为 Gemini 系列\n"
            f"· 对话模型切换为 gemini-3-flash-preview\n"
            f"· 暂时移除图片生成功能，仅保留对话\n"
            f"· NapCat WebSocket 稳定性修复：心跳/超时/挂起请求清理\n"
            f"· 适配 bridge 心跳与状态包，避免误报连接已关闭\n"
            f"· AI 单 API 并发上限调整为 10\n"
            f"\n"
            f"v3.0.3 (2026-03-29)\n"
            f"· 新增 /授权q QQ号：个人功能授权\n"
            f"· 新增 /授权群 群号：群功能授权\n"
            f"· /nfa 现支持管理员、个人白名单、群白名单三种权限来源\n"
            f"· /admin、/staff、/status、帮助文案同步补充 NFA 白名单统计\n"
            f"\n"
            f"v3.0.2 (2026-03-29)\n"
            f"· 新增 /取消授权 群号：将群移出 NFA 白名单\n"
            f"· /授权群 与 /取消授权 现已支持整群开关功能权限\n"
            f"· /admin、/staff、帮助文案同步补充群授权管理指令\n"
            f"\n"
            f"v3.0.1 (2026-03-29)\n"
            f"· 新增 /授权 群号：将群加入 NFA 白名单\n"
            f"· 被授权群内所有成员都可在群内直接使用 /nfa\n"
            f"· /admin 与 /status 新增 NFA 群授权统计\n"
            f"\n"
            f"v3.0.0 (2026-03-29)\n"
            f"· AI 对话全面升级：猫娘提示词重写，萌+智兼顾\n"
            f"· AI 回复质量提升：max_tokens 800→2048，回复更充实\n"
            f"· 支持多段回复：AI 用 [---SPLIT---] 自动分段发送\n"
            f"· 参数调优：temperature 0.7 + top_p 0.9\n"
            f"· 新增「赞我」功能：@曦曦 赞我，自动主页点赞20个\n"
            f"· 新增「今日人品」功能：每日人品值 + 分区间趣味回复\n"
            f"· 新增 QQ 表情(face)智能回复：70+种表情映射\n"
            f"· 新增表情包(mface)识别回复 + 自动收集系统\n"
            f"· AI 回复支持发送表情包：[sticker:关键词] 替换\n"
            f"· AI 多线程并发优化：curl→httpx 异步连接池\n"
            f"· 新增并发信号量控制 + AI 并发实时统计\n"
            f"· 修复抖音解析：海外服务器短链接多重降级策略\n"
            f"· 抖音解析支持 QQ JSON/XML 分享卡片提取链接\n"
            f"· 内容安全规范全面加强，防注入/防绕过\n"
            f"\n"
            f"v2.9.6 (2026-03-29)\n"
            f"· 网页爬虫升级：深度分析+子链接自动跟进探索\n"
            f"· AI 多条消息输出，分步深入分析网页内容\n"
            f"· 智能发现页面子链接并自动抓取补充信息\n"
            f"· 分析完成后自动给出总结评价和建议\n"
            f"\n"
            f"v2.9.5 (2026-03-29)\n"
            f"· 新增网页爬虫+AI分析（消息中包含URL时自动抓取喂给AI）\n"
            f"· 支持@曦曦甩链接+提问，AI基于网页内容回答\n"
            f"\n"
            f"v2.9.4 (2026-03-29)\n"
            f"· 新增 Staff 员工权限系统（/staff /addstaff /deletestaff）\n"
            f"· Staff 拥有与Admin相同权限（除/nfa和/addstaff外）\n"
            f"· Staff 支持自设密码登陆，重启后需重新验证\n"
            f"· /admin 面板新增 Staff 列表与状态显示\n"
            f"\n"
            f"v2.9.3 (2026-03-28)\n"
            f"· 新增 /admin 管理后台面板（查看管理员/封禁列表）\n"
            f"· 新增 /ban /unban 封禁系统（被封禁用户无法使用Bot）\n"
            f"· 管理员与封禁列表持久化存储\n"
            f"\n"
            f"v2.9.2 (2026-03-28)\n"
            f"· 内存优化：缓存自动清理 + 过期淘汰 + 上限控制\n"
            f"· 撤回/群聊/AI历史缓存截断 + LRU淘汰\n"
            f"· 消息队列上限防溢出 + 重连自动清理\n"
            f"· 点歌/广播/抽奖状态超时自动回收\n"
            f"\n"
            f"v2.9.1 (2026-03-28)\n"
            f"· /hh 支持交互式选群广播（序号/范围/all）\n"
            f"· 修复 /shutdown 关机后不会自动拉起的问题\n"
            f"· 修复重启通知重复发送3次的问题\n"
            f"· 广播防风控间隔优化（1.5s+每5群3s）\n"
            f"\n"
            f"v2.9.0 (2026-03-28)\n"
            f"· 新增 /check 查看Bot群聊/好友数量\n"
            f"· 新增 /hh 全群广播（需admin权限）\n"
            f"\n"
            f"v2.8.2 (2026-03-28)\n"
            f"· /auth 统一管理权限验证（密码登陆）\n"
            f"· /nfa、/shutdown 改为需 /auth 登陆后使用\n"
            f"· 移除 VIP_QQ 硬编码权限检查\n"
            f"\n"
            f"v2.8.1 (2026-03-28)\n"
            f"· 修复抖音链接被B站解析拦截的bug（调整检测顺序）\n"
            f"· bilibili模块新增抖音域名排除保护\n"
            f"\n"
            f"v2.8.0 (2026-03-28)\n"
            f"· 新增 /shutdown 远程关机（立即/定时/取消）\n"
            f"\n"
            f"v2.7.0 (2026-03-28)\n"
            f"· 新增 /dashboard 系统仪表盘（系统/QQ/Bot信息）\n"
            f"· 新增 /showlottery 查看抽奖奖品保险箱\n"
            f"· 新增 /datalog 完整更新日志\n"
            f"· /status 更新日志精简为仅当前版本\n"
            f"\n"
            f"v2.6.1 (2026-03-28)\n"
            f"· 修复抖音链接被误识别为B站av号的问题\n"
            f"\n"
            f"v2.6.0 (2026-03-28)\n"
            f"· 抖音解析重写：双通道解析 + 地区限制提示\n"
            f"· 4399 sauth 并发支持：共享连接池 + 限流\n"
            f"· 图片生成多Key轮换重试机制\n"
            f"· 新增 /status 状态查询\n"
            f"· 新增 Hypixel 封禁追踪 /hypban\n"
            f"· 支持 /hypban on|off 自动播报\n"
            f"· 图片生成切换至 grok-imagine 引擎\n"
            f"· 4399 sauth 增加重试 + 502容错\n"
            f"· AI 性能优化：群聊上下文独立缓存\n"
            f"· 消息发送增加断线重试\n"
            f"━━━━━━━━━━━━━━━━━"
        )
        await send_reply(ws, message_type, user_id, group_id, changelog)
        _log.info(f"[更新日志] {nickname} 查询完整日志")
        return True

    # 机器人状态查询
    if content in ("/status", "status"):
        uptime_sec = int(_time_mod.time() - _start_time)
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        if days > 0:
            uptime_str = f"{days}天{hours}小时{minutes}分钟"
        elif hours > 0:
            uptime_str = f"{hours}小时{minutes}分钟"
        else:
            uptime_str = f"{minutes}分钟{secs}秒"

        # 统计信息
        cache_count = len(_msg_cache)
        group_cache_count = sum(len(v) for v in _group_chat_cache.values())
        group_cache_groups = len(_group_chat_cache)
        queue_size = _msg_queue.qsize()
        hypban_active = sum(1 for t in _hypban_tasks.values() if not t.done())
        api_key_count = len(api_keys)
        admin_count = len(_admin_authorized)
        banned_count = len(_banned_users)
        nfa_user_count = len(_nfa_user_authorized)
        nfa_group_count = len(_nfa_group_authorized)

        # AI 并发统计
        ai_stats = ai_chat.get_stats()

        status_text = (
            f"曦曦 Bot v{BOT_VERSION}\n"
            f"━━━━━ 运行状态 ━━━━━\n"
            f"运行时间：{uptime_str}\n"
            f"消息缓存：{cache_count}/{MAX_CACHE} 条\n"
            f"群聊上下文：{group_cache_groups} 个群 / {group_cache_count} 条\n"
            f"待处理队列：{queue_size} 条\n"
            f"并发 Worker：{MSG_WORKERS} 个\n"
            f"API Key：{api_key_count} 个\n"
            f"AI 并发：{ai_stats['active']}/{ai_stats['max_concurrent']} "
            f"(成功:{ai_stats['success']} 失败:{ai_stats['failed']})\n"
            f"表情包库：{fun.get_sticker_count()} 个\n"
            f"Hypban 自动播报：{hypban_active} 个群\n"
            f"管理员：{admin_count} 人 | 封禁：{banned_count} 人\n"
            f"Staff：{len(_staff)} 人（{len(_staff_logged_in)} 人在线）\n"
            f"NFA 个人授权：{nfa_user_count} 人\n"
            f"NFA 群授权：{nfa_group_count} 个\n"
            f"AI 模型：{ai_config.get('model', '未知')}\n"
            f"━━━ v{BOT_VERSION} 更新日志 ━━━\n"
            f"· 新增邮件发送 nfa/4399/163\n"
            f"· 新增 /bind 邮箱 /unbind\n"
            f"· AI 模型切换为 gemini-3-flash-preview\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"发送 /datalog 查看完整更新日志\n"
            f"构建日期：{BOT_BUILD_DATE}"
        )
        await send_reply(ws, message_type, user_id, group_id, status_text)
        _log.info(f"[Status] {nickname} 查询状态")
        return True

    # 重启指令（需要 Admin 或 Staff 权限）
    if content.startswith("/shutdown") or content.startswith("shutdown"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要管理权限喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        global _restart_task
        args = content.split(None, 1)
        param = args[1].strip() if len(args) > 1 else ""

        # 取消计划重启
        if param == "-c":
            if _restart_task and not _restart_task.done():
                _restart_task.cancel()
                _restart_task = None
                await send_reply(
                    ws, message_type, user_id, group_id, "✅ 已取消计划重启喵~"
                )
            else:
                await send_reply(
                    ws, message_type, user_id, group_id, "当前没有计划中的重启喵~"
                )
            return True

        # 立即重启
        if param == "now" or param == "":
            await _send_raw(
                ws, message_type, user_id, group_id, "🔄 正在重启喵，请稍等..."
            )
            _log.info(f"[Restart] {nickname} 触发立即重启")
            _write_restart_flag(message_type, user_id, group_id)
            await asyncio.sleep(0.5)
            _do_restart()
            return True

        # 定时重启: /restart -5 表示 5 分钟后
        if param.startswith("-"):
            try:
                minutes = int(param[1:])
            except ValueError:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "格式错误喵！用法：/shutdown -分钟数（如 /shutdown -5）",
                )
                return True

            if minutes <= 0:
                await send_reply(
                    ws, message_type, user_id, group_id, "时间必须大于 0 喵！"
                )
                return True

            # 取消旧的计划
            if _restart_task and not _restart_task.done():
                _restart_task.cancel()

            from datetime import timedelta as _td

            restart_time = datetime.now() + _td(minutes=minutes)
            time_str = restart_time.strftime("%Y-%m-%d %H:%M:%S")

            async def _scheduled_restart():
                try:
                    await asyncio.sleep(minutes * 60)
                    await _send_raw(
                        ws,
                        message_type,
                        user_id,
                        group_id,
                        "🔄 计划重启时间已到，正在重启喵...",
                    )
                    _log.info(f"[Restart] 计划重启执行")
                    _write_restart_flag(message_type, user_id, group_id)
                    await asyncio.sleep(0.5)
                    _do_restart()
                except asyncio.CancelledError:
                    _log.info("[Restart] 计划重启已取消")

            _restart_task = asyncio.create_task(_scheduled_restart())
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f'🔄 计划于 {time_str} 关机，使用"/shutdown -c"以取消。',
            )
            _log.info(f"[Restart] {nickname} 计划 {minutes} 分钟后重启")
            return True

        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            "用法：/shutdown now | /shutdown -分钟数 | /shutdown -c",
        )
        return True

    # Bot 信息查询（群/好友数量）
    if content in ("/check", "check"):
        try:
            # 获取群列表
            grp_resp = await send_api_request(ws, "get_group_list", {}, timeout=10)
            group_count = 0
            if grp_resp.get("retcode") == 0:
                group_count = len(grp_resp.get("data", []))

            # 获取好友列表
            fri_resp = await send_api_request(ws, "get_friend_list", {}, timeout=10)
            friend_count = 0
            if fri_resp.get("retcode") == 0:
                friend_count = len(fri_resp.get("data", []))

            check_text = (
                f"📊 曦曦 Bot 社交概况\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"加入群聊：{group_count} 个\n"
                f"好友数量：{friend_count} 个\n"
                f"━━━━━━━━━━━━━━━━━"
            )
        except Exception as e:
            _log.error(f"[Check] 获取信息失败: {e}")
            check_text = "获取信息失败了喵~请稍后再试"

        await send_reply(ws, message_type, user_id, group_id, check_text)
        _log.info(f"[Check] {nickname} 查询Bot信息: 群{group_count} 好友{friend_count}")
        return True

    # 全群广播 / 选群广播（需要 Admin 或 Staff 权限）
    if content == "/hh" or content.startswith("/hh ") or content.startswith("/hh:"):
        if not _is_admin_or_staff(user_id):
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "该指令需要管理权限喵~请先私聊曦曦发送 /auth 验证码 进行验证",
            )
            return True

        user_key = f"{message_type}_{group_id}_{user_id}"
        param = content[3:].lstrip(":").strip() if len(content) > 3 else ""

        # /hh all 内容 → 直接全群广播
        if param.startswith("all ") or param.startswith("all:"):
            broadcast_msg = param[3:].lstrip(":").strip()
            if broadcast_msg:
                asyncio.create_task(
                    _do_broadcast(
                        ws,
                        message_type,
                        user_id,
                        group_id,
                        nickname,
                        broadcast_msg,
                        None,
                    )
                )
                return True

        # /hh 内容（没有 all）→ 直接全群广播（兼容旧用法）
        if param and not param.startswith("all"):
            asyncio.create_task(
                _do_broadcast(
                    ws, message_type, user_id, group_id, nickname, param, None
                )
            )
            return True

        # /hh（无参数）→ 进入选群模式
        try:
            grp_resp = await send_api_request(ws, "get_group_list", {}, timeout=10)
            if grp_resp.get("retcode") != 0:
                await send_reply(
                    ws, message_type, user_id, group_id, "获取群列表失败了喵~"
                )
                return True
            groups = grp_resp.get("data", [])
        except Exception as e:
            _log.error(f"[广播] 获取群列表失败: {e}")
            await send_reply(ws, message_type, user_id, group_id, "获取群列表失败了喵~")
            return True

        if not groups:
            await send_reply(
                ws, message_type, user_id, group_id, "当前没有加入任何群喵~"
            )
            return True

        # 构建群列表文本
        lines = ["📢 请选择要喊话的群：", "━━━━━━━━━━━━━━━━━"]
        for i, g in enumerate(groups):
            name = g.get("group_name", "未知群")
            gid = g.get("group_id", 0)
            lines.append(f"{i + 1}. {name} ({gid})")
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("回复序号选择，如：1,3,5 或 1-7 或 all")
        lines.append("回复「取消」可取消操作")

        _hh_waiting[user_key] = {
            "step": "select_group",
            "groups": groups,
            "expire": _time_mod.time() + 300,
        }
        await send_reply(ws, message_type, user_id, group_id, "\n".join(lines))
        _log.info(f"[广播] {nickname} 进入选群模式，共 {len(groups)} 个群")
        return True

    # 系统仪表盘
    if content in ("/dashboard", "dashboard"):
        import shutil

        # ---- 系统信息 ----
        uname = platform.uname()
        os_info = f"{uname.system} {uname.release}"
        cpu_model = uname.processor or platform.processor() or "未知"
        if len(cpu_model) > 40:
            cpu_model = cpu_model[:40] + "..."
        cpu_threads = os.cpu_count() or "?"

        # 优先使用 psutil 获取内存信息；Windows 新版本常常没有 wmic
        mem_total_str = "?"
        mem_used_str = "?"
        mem_pct_str = "?"
        try:
            import psutil

            mem = psutil.virtual_memory()
            mem_total_str = f"{mem.total / (1024**3):.1f}"
            mem_used_str = f"{mem.used / (1024**3):.1f}"
            mem_pct_str = f"{mem.percent:.1f}"
        except Exception:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "wmic",
                    "OS",
                    "get",
                    "TotalVisibleMemorySize,FreePhysicalMemory",
                    "/value",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                raw = stdout.decode("utf-8", errors="replace")
                free_kb = total_kb = 0
                for line in raw.splitlines():
                    if line.startswith("TotalVisibleMemorySize="):
                        total_kb = int(line.split("=")[1].strip())
                    elif line.startswith("FreePhysicalMemory="):
                        free_kb = int(line.split("=")[1].strip())
                if total_kb:
                    used_kb = total_kb - free_kb
                    mem_total_str = f"{total_kb / (1024 * 1024):.1f}"
                    mem_used_str = f"{used_kb / (1024 * 1024):.1f}"
                    mem_pct_str = f"{used_kb / total_kb * 100:.1f}"
            except Exception:
                pass

        # 磁盘信息（stdlib shutil）
        disk = shutil.disk_usage(".")
        disk_total = f"{disk.total / (1024**3):.1f}"
        disk_used = f"{disk.used / (1024**3):.1f}"
        disk_pct = f"{disk.used / disk.total * 100:.1f}"

        py_ver = platform.python_version()

        # ---- 运行时间 ----
        uptime_sec = int(_time_mod.time() - _start_time)
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        if days > 0:
            uptime_str = f"{days}天{hours}小时{minutes}分钟"
        elif hours > 0:
            uptime_str = f"{hours}小时{minutes}分钟"
        else:
            uptime_str = f"{minutes}分钟{secs}秒"

        # ---- QQ/NapCat 版本 (OneBot API) ----
        qq_ver = "获取失败"
        napcat_ver = "获取失败"
        try:
            ver_resp = await send_api_request(ws, "get_version_info", {}, timeout=5)
            if ver_resp.get("retcode") == 0:
                ver_data = ver_resp.get("data", {})
                qq_ver = ver_data.get("app_version", ver_data.get("nt_version", "未知"))
                napcat_ver = ver_data.get("version", ver_data.get("app_name", "未知"))
        except Exception:
            pass

        # ---- 登录信息 ----
        login_nick = "未知"
        login_qq = "未知"
        try:
            login_resp = await send_api_request(ws, "get_login_info", {}, timeout=5)
            if login_resp.get("retcode") == 0:
                login_data = login_resp.get("data", {})
                login_nick = login_data.get("nickname", "未知")
                login_qq = login_data.get("user_id", "未知")
        except Exception:
            pass

        dashboard = (
            f"📊 曦曦 Bot 系统仪表盘\n"
            f"━━━━━ 🖥️ 系统信息 ━━━━━\n"
            f"操作系统：{os_info}\n"
            f"处理器：{cpu_model}\n"
            f"CPU：{cpu_threads} 线程\n"
            f"内存：{mem_used_str}G / {mem_total_str}G ({mem_pct_str}%)\n"
            f"磁盘：{disk_used}G / {disk_total}G ({disk_pct}%)\n"
            f"Python：{py_ver}\n"
            f"━━━━━ 💬 QQ 信息 ━━━━━\n"
            f"NapCat：{napcat_ver}\n"
            f"QQ 版本：{qq_ver}\n"
            f"登录账号：{login_nick} ({login_qq})\n"
            f"━━━━━ 🤖 Bot 信息 ━━━━━\n"
            f"Bot 版本：v{BOT_VERSION}\n"
            f"运行时间：{uptime_str}\n"
            f"构建日期：{BOT_BUILD_DATE}"
        )
        await send_reply(ws, message_type, user_id, group_id, dashboard)
        _log.info(f"[Dashboard] {nickname} 查询系统仪表盘")
        return True

    # 赞我
    if content in ("赞我", "点赞", "给我点赞"):

        async def _do_like(u_id):
            return await send_api_request(
                ws,
                "send_like",
                {
                    "user_id": u_id,
                    "times": 10,
                },
                timeout=10,
            )

        try:
            total_liked = 0
            for _ in range(2):  # 尝试点2轮共20赞
                resp = await send_api_request(
                    ws,
                    "send_like",
                    {
                        "user_id": user_id,
                        "times": 10,
                    },
                    timeout=10,
                )
                if resp.get("retcode") == 0:
                    total_liked += 10
                else:
                    break
            if total_liked > 0:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"已为你点赞 {total_liked} 个喵~去主页看看吧！",
                )
            else:
                error_msg = resp.get("message", resp.get("wording", "未知错误"))
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"点赞失败了喵~（{error_msg}）可能今天已经赞过啦",
                )
        except Exception as e:
            _log.error(f"[赞我] 点赞异常: {e}")
            await send_reply(
                ws, message_type, user_id, group_id, "点赞出错了喵~请稍后再试"
            )
        _log.info(f"[赞我] {nickname}({user_id}) 点赞{total_liked}个")
        return True

    # 今日人品
    if content in ("今日人品", "人品", "jrrp", "/jrrp"):
        result = fun.get_jrrp(str(user_id), nickname)
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[今日人品] {nickname} 查询人品")
        return True

    # 运势/抽签
    if content in ("运势", "今日运势", "抽签", "每日运势"):
        result = fun.get_fortune()
        await send_reply(ws, message_type, user_id, group_id, result)
        _log.info(f"[运势] {nickname}")
        return True

    # 天气查询
    weather_match = re.match(r"(.+?)天气$", content)
    if weather_match:
        city = weather_match.group(1).strip()
        if city:
            result = await fun.get_weather(city)
            await send_reply(ws, message_type, user_id, group_id, result)
            _log.info(f"[天气] {city}")
            return True

    # 清除记忆
    if content in ("清除记忆", "重置对话", "清空对话"):
        chat_id = f"g{group_id}_{user_id}" if message_type == "group" else str(user_id)
        ai_chat.clear_history(chat_id)
        await send_reply(
            ws, message_type, user_id, group_id, "对话记忆已清除，我们重新开始吧喵~"
        )
        _log.info(f"[清除记忆] {nickname}")
        return True

    # ===== 空调系统（仅群聊） =====
    if message_type == "group":
        ac_cmd = content.lower().strip()
        ac_result = None

        if ac_cmd in ("开空调", "/开空调"):
            ac_result = aircon.cmd_turn_on(group_id)
        elif ac_cmd in ("关空调", "/关空调"):
            ac_result = aircon.cmd_turn_off(group_id)
        elif ac_cmd in ("空调状态", "/空调状态", "看空调"):
            ac_result = aircon.cmd_ac_status(group_id)
        elif ac_cmd in ("换空调", "/换空调", "新空调"):
            ac_result = aircon.cmd_change_ac(group_id)
        elif ac_cmd in (
            "空调炸炸排行榜",
            "/空调排行",
            "炸炸排行榜",
            "空调排行榜",
            "炸炸排行",
        ):
            rank_text = aircon.cmd_boom_rank()
            await send_reply(ws, message_type, user_id, group_id, rank_text)
            return True
        else:
            raise_match = re.match(r"^(空调升温|/空调升温)\s*(\d*)$", ac_cmd)
            lower_match = re.match(r"^(空调降温|/空调降温)\s*(\d*)$", ac_cmd)
            if raise_match:
                amount = int(raise_match.group(2)) if raise_match.group(2) else 5
                amount = min(amount, 50)
                ac_result = aircon.cmd_raise_temp(group_id, amount)
            elif lower_match:
                amount = int(lower_match.group(2)) if lower_match.group(2) else 5
                amount = min(amount, 50)
                ac_result = aircon.cmd_lower_temp(group_id, amount)

        if ac_result is not None:
            text, img_path = ac_result
            if img_path:
                img_msg = f"[CQ:image,file=file:///{img_path}]\n{text}"
                await send_reply(ws, message_type, user_id, group_id, img_msg)
            else:
                await send_reply(ws, message_type, user_id, group_id, text)
            _log.info(f"[空调] {nickname}({user_id}) {ac_cmd}")
            return True

    # 点歌
    if content in ("点歌", "听歌", "来首歌"):
        user_key = f"{message_type}_{group_id}_{user_id}"
        _music_waiting[user_key] = _time_mod.time()
        await send_reply(
            ws, message_type, user_id, group_id, "主人想听什么歌呢？告诉曦曦歌名吧喵~"
        )
        _log.info(f"[点歌] {nickname} 进入点歌模式")
        return True

    # 点歌直接带歌名：点歌 晴天
    if (
        content.startswith("点歌 ")
        or content.startswith("点歌：")
        or content.startswith("点歌:")
    ):
        song_name = content.split(None, 1)[-1].lstrip("：:").strip()
        if song_name:
            return await _do_search_music(
                ws, message_type, user_id, group_id, song_name, nickname
            )

    # GitHub 搜索
    gh_match = re.match(r"(?:搜索|搜|search)\s*[Gg]it[Hh]ub\s+(.+)", content)
    if not gh_match:
        gh_match = re.match(r"[Gg]it[Hh]ub\s*(?:搜索|搜)\s+(.+)", content)
    if gh_match:
        keyword = gh_match.group(1).strip()
        if keyword:
            return await _do_search_github(
                ws, message_type, user_id, group_id, keyword, nickname
            )

    return False


def _parse_group_selection(text: str, total: int) -> list[int] | None:
    """解析用户的群选择输入，返回 0-based 索引列表，无效返回 None"""
    text = text.strip()
    if text.lower() == "all":
        return list(range(total))

    indices = set()
    parts = re.split(r"[,，\s]+", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 范围：1-7
        range_match = re.match(r"^(\d+)\s*[-~到]\s*(\d+)$", part)
        if range_match:
            a, b = int(range_match.group(1)), int(range_match.group(2))
            if a < 1 or b > total or a > b:
                return None
            indices.update(range(a - 1, b))
            continue
        # 单个数字
        if part.isdigit():
            n = int(part)
            if n < 1 or n > total:
                return None
            indices.add(n - 1)
            continue
        return None  # 无法识别

    return sorted(indices) if indices else None


async def _do_broadcast(
    ws, message_type, user_id, group_id, nickname, broadcast_msg, selected_groups
):
    """
    执行广播发送
    selected_groups: 群信息列表，为 None 时自动获取全部群
    """
    token = _command_ads_enabled.set(False)
    try:
        if selected_groups is None:
            try:
                grp_resp = await send_api_request(ws, "get_group_list", {}, timeout=10)
                if grp_resp.get("retcode") != 0:
                    await send_reply(
                        ws, message_type, user_id, group_id, "获取群列表失败了喵~"
                    )
                    return
                selected_groups = grp_resp.get("data", [])
            except Exception as e:
                _log.error(f"[广播] 获取群列表失败: {e}")
                await send_reply(
                    ws, message_type, user_id, group_id, "获取群列表失败了喵~"
                )
                return

        total = len(selected_groups)
        if total == 0:
            await send_reply(ws, message_type, user_id, group_id, "没有可广播的群喵~")
            return

        await send_reply(
            ws, message_type, user_id, group_id, f"📢 开始向 {total} 个群广播消息..."
        )
        _log.info(f"[广播] {nickname} 发起广播({total}群): {broadcast_msg[:50]}")

        success = 0
        fail = 0
        for i, g in enumerate(selected_groups):
            gid = g.get("group_id") if isinstance(g, dict) else g
            if not gid:
                fail += 1
                continue
            try:
                await send_group_msg(ws, gid, broadcast_msg)
                success += 1
                if (i + 1) % 5 == 0:
                    await asyncio.sleep(3)
                else:
                    await asyncio.sleep(1.5)
            except Exception as e:
                _log.warning(f"[广播] 群{gid}发送失败: {e}")
                fail += 1

        result_text = f"📢 广播完成！成功 {success}/{total} 个群"
        if fail > 0:
            result_text += f"（{fail} 个失败）"
        await send_reply(ws, message_type, user_id, group_id, result_text)
        _log.info(f"[广播] 完成: 成功{success} 失败{fail} 共{total}")
    finally:
        _command_ads_enabled.reset(token)


async def _do_search_music(
    ws, message_type, user_id, group_id, song_name, nickname
) -> bool:
    """搜索音乐并展示选择列表"""
    _log.info(f"[点歌] {nickname} 搜索: {song_name}")
    songs = await music.search_music(song_name, limit=5)
    if songs:
        user_key = f"{message_type}_{group_id}_{user_id}"
        music.set_waiting(user_key, songs)
        list_text = music.build_song_list(songs)
        await send_reply(ws, message_type, user_id, group_id, list_text)
        _log.info(f"[点歌] 展示列表: {len(songs)} 首")
    else:
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            f"没有找到「{song_name}」这首歌呢喵~换个名字试试？",
        )
        _log.info(f"[点歌] 未找到: {song_name}")
    return True


async def _do_search_github(
    ws, message_type, user_id, group_id, keyword, nickname
) -> bool:
    """搜索 GitHub 并展示选择列表"""
    _log.info(f"[GitHub] {nickname} 搜索: {keyword}")
    repos = await github.search_repos(keyword, limit=5)
    if repos:
        user_key = f"{message_type}_{group_id}_{user_id}"
        github.set_waiting(user_key, repos)
        list_text = github.build_repo_list(repos)
        await send_reply(ws, message_type, user_id, group_id, list_text)
        _log.info(f"[GitHub] 展示列表: {len(repos)} 个仓库")
    else:
        await send_reply(
            ws, message_type, user_id, group_id, f"没有找到「{keyword}」相关的仓库呢喵~"
        )
        _log.info(f"[GitHub] 未找到: {keyword}")
    return True


async def bjd_check_loop(ws):
    """布吉岛定时播报：仅在12:00和18:00各播报一次"""
    from datetime import datetime

    last_broadcast_hour = -1
    token = _command_ads_enabled.set(False)

    try:
        while True:
            try:
                # 检测 WS 状态，若已断开则销毁此老任务，防止泄露
                if getattr(ws, "closed", getattr(ws, "state", 0) == 3):
                    _log.info("[布吉岛] WebSocket已断开，停止定时播报任务")
                    break

                await asyncio.sleep(60)  # 每分钟检查一次时间

                now = datetime.now()

                # 定时播报：12:00 和 18:00
                if now.hour in (12, 18) and now.hour != last_broadcast_hour:
                    if not _bjd_sub_groups:
                        last_broadcast_hour = now.hour
                        continue
                    info = await bjd.get_latest_version()
                    if not info:
                        continue
                    last_broadcast_hour = now.hour
                    msg = bjd.build_update_msg(info, is_update=False)
                    groups = list(_bjd_sub_groups)
                    _log.info(
                        f"[布吉岛] 定时播报: v{info['version']} -> {len(groups)}个群"
                    )
                    for i, gid in enumerate(groups):
                        try:
                            await send_group_msg(ws, gid, msg)
                        except Exception as e:
                            _log.warning(f"[布吉岛] 群{gid}播报失败: {e}")
                        if i < len(groups) - 1:
                            await asyncio.sleep(2)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _log.warning(f"[布吉岛] 检测出错: {e}")
    finally:
        _command_ads_enabled.reset(token)


async def _hypban_auto_loop(ws, group_id: int):
    """Hypixel 封禁统计每分钟自动播报后台任务"""
    token = _command_ads_enabled.set(False)
    try:
        while True:
            if getattr(ws, "closed", getattr(ws, "state", 0) == 3):
                _log.info(f"[Hypixel] WebSocket已断开，停止群{group_id}自动播报")
                break
            await asyncio.sleep(60)
            result = await hypban.get_ban_stats()
            await send_group_msg(ws, group_id, result)
    except asyncio.CancelledError:
        _log.info(f"[Hypixel] 群{group_id} 自动播报已取消")
    except Exception as e:
        _log.warning(f"[Hypixel] 群{group_id} 自动播报出错: {e}")
    finally:
        _command_ads_enabled.reset(token)
        _hypban_tasks.pop(group_id, None)


async def lottery_check_loop(ws):
    """抽奖定时检查后台任务，脱离单个创建会话，支持断线重连恢复"""
    from handlers import lottery

    while True:
        try:
            if getattr(ws, "closed", getattr(ws, "state", 0) == 3):
                _log.info("[后台任务] WebSocket 断开，退出抽奖监测任务")
                break

            expired_groups = lottery.get_expired_lotteries()
            for gid in expired_groups:
                await lottery.do_draw(
                    gid,
                    lambda m, group_id=gid: send_group_msg(ws, group_id, m),
                    lambda uid, m: send_api_request(
                        ws, "send_private_msg", {"user_id": uid, "message": m}
                    ),
                )

            await asyncio.sleep(2)  # 每 2 秒检查一次
        except asyncio.CancelledError:
            break
        except Exception as e:
            _log.error(f"[抽奖检查] 出错: {e}")
            await asyncio.sleep(2)


async def _cleanup_caches(ws):
    """定时缓存清理任务：每10分钟执行一次，防止内存无限增长"""
    while True:
        try:
            if getattr(ws, "closed", getattr(ws, "state", 0) == 3):
                _log.info("[缓存清理] WebSocket已断开，停止清理任务")
                break

            await asyncio.sleep(600)  # 每10分钟清理一次

            cleaned = 0

            # 1. 清理B站去重过期条目
            now_ts = _time_mod.time()
            for gid in list(_bili_parsed.keys()):
                expired_keys = [
                    k
                    for k, t in _bili_parsed[gid].items()
                    if now_ts - t > BILI_DEDUP_EXPIRE
                ]
                for k in expired_keys:
                    del _bili_parsed[gid][k]
                    cleaned += 1
                if not _bili_parsed[gid]:
                    del _bili_parsed[gid]

            # 2. 清理过期的点歌/GitHub选择状态
            music.cleanup_expired()
            github.cleanup_expired()

            # 3. 清理抽奖创建超时会话
            from handlers import lottery

            lottery.cleanup_stale_sessions()

            # 4. 清理AI对话不活跃用户
            cleaned_ai = ai_chat.cleanup_inactive(max_age=7200)
            cleaned += cleaned_ai

            # 5. 清理过期的点歌等待
            expired_music = [k for k, ts in _music_waiting.items() if now_ts - ts > 60]
            for k in expired_music:
                del _music_waiting[k]
                cleaned += 1

            # 6. 清理过期的广播等待
            expired_hh = [
                k
                for k, v in _hh_waiting.items()
                if now_ts > v.get("expire", float("inf"))
            ]
            for k in expired_hh:
                del _hh_waiting[k]
                cleaned += 1

            # 7. 清理过期的删除Staff选择状态
            expired_ds = [
                k
                for k, v in _deletestaff_waiting.items()
                if now_ts > v.get("expire", float("inf"))
            ]
            for k in expired_ds:
                del _deletestaff_waiting[k]
                cleaned += 1

            # 8. 清理过期的模糊指令确认状态
            expired_command_hints = [
                k
                for k, v in _command_hint_waiting.items()
                if now_ts > v.get("expire", float("inf"))
            ]
            for k in expired_command_hints:
                del _command_hint_waiting[k]
                cleaned += 1

            # 9. 清理过期的广告列表查看状态
            expired_ad_waiting = [k for k, ts in _ad_waiting.items() if now_ts > ts]
            for k in expired_ad_waiting:
                del _ad_waiting[k]
                cleaned += 1

            # 10. 清理到期广告的展示状态
            old_enabled = sum(1 for ad in _ads if ad.get("enabled"))
            _cleanup_expired_ads(save=True)
            new_enabled = sum(1 for ad in _ads if ad.get("enabled"))
            if new_enabled != old_enabled:
                cleaned += abs(old_enabled - new_enabled)

            if cleaned > 0:
                _log.info(f"[缓存清理] 清理了 {cleaned} 条过期数据")

        except asyncio.CancelledError:
            break
        except Exception as e:
            _log.warning(f"[缓存清理] 出错: {e}")


# ====== 深度网页爬虫 + AI 分析 ======
# 最多跟进爬取的子链接数
DEEP_CRAWL_MAX_SUBLINKS = 3
# 深度分析时 AI 的 max_tokens
DEEP_CRAWL_MAX_TOKENS = 4096


async def _deep_crawl_analyze(
    ws, message_type, user_id, group_id, chat_id, url, original_content
):
    """
    深度网页爬虫 + AI 分析流程（后台任务）
    1. 抓取主页面 → AI 第一轮分析（总结 + 发现）
    2. AI 判断是否需要跟进子链接 → 自动爬取感兴趣的子链接
    3. 综合所有信息 → AI 第二轮深度分析（多条消息输出）
    """
    try:
        # ===== 第一步：抓取主页面 =====
        success, html_or_err = await web_crawler.fetch_page(url)
        if not success:
            await send_reply(
                ws, message_type, user_id, group_id, f"网页抓取失败了喵~{html_or_err}"
            )
            return

        page_info = web_crawler.extract_content(html_or_err, url)
        links_text = web_crawler.build_links_text(page_info.get("links", []))

        # 提取用户的问题部分
        user_question = original_content.replace(url, "").strip()
        if not user_question:
            user_question = "请深入分析这个网页的内容，告诉我这个网站是做什么的，有什么特色和值得关注的点"

        _log.info(f"[深度爬虫] 主页面抓取成功: {page_info['title'][:50]}")

        # ===== 第二步：AI 第一轮分析 =====
        # 构建第一轮分析的增强 prompt
        first_prompt = (
            f"[深度网页分析任务 - 第一步]\n"
            f"我给你一个网页的内容，请你先仔细阅读并回答我的问题。\n\n"
            f"网页标题：{page_info['title']}\n"
            f"网页描述：{page_info['description']}\n"
            f"网页正文：{page_info['content']}\n"
            f"网页链接：{page_info['url']}\n"
        )
        if links_text:
            first_prompt += f"\n页面中发现的链接：\n{links_text}\n"
        first_prompt += (
            f"\n我的问题：{user_question}\n\n"
            f"请先回答我的问题。回答完毕后，如果你觉得页面中的某些链接值得进一步探索来补充信息，"
            f"请在回答的最后另起一行，用这个格式列出你想探索的链接（最多{DEEP_CRAWL_MAX_SUBLINKS}个）：\n"
            f"[EXPLORE_LINKS]\n"
            f"链接1\n"
            f"链接2\n"
            f"[/EXPLORE_LINKS]\n"
            f"如果你觉得不需要进一步探索，就不用加这个标记。"
        )

        group_ctx = (
            _group_chat_cache.get(group_id, []) if message_type == "group" else []
        )
        first_reply = await ai_chat.chat(chat_id, first_prompt, group_context=group_ctx)

        # 从 AI 回复中提取要探索的链接
        explore_urls = []
        import re as _re

        explore_match = _re.search(
            r"\[EXPLORE_LINKS\]\s*\n(.*?)\[/EXPLORE_LINKS\]", first_reply, _re.DOTALL
        )
        if explore_match:
            raw_links = explore_match.group(1).strip().split("\n")
            for link in raw_links:
                link = link.strip()
                if web_crawler.is_valid_url(link):
                    explore_urls.append(link)
            # 清理 AI 回复中的链接标记
            first_reply = first_reply[: explore_match.start()].rstrip()

        # 发送第一条消息（主页面分析结果）
        msg1 = f"🌐 网页深度分析 | {page_info['title']}\n"
        msg1 += f"━━━━━━━━━━━━━━\n"
        msg1 += first_reply
        await send_reply(ws, message_type, user_id, group_id, msg1)
        _log.info(f"[深度爬虫] 第一轮分析完成，发现 {len(explore_urls)} 个待探索链接")

        # ===== 第三步：跟进子链接 =====
        if explore_urls:
            explore_urls = explore_urls[:DEEP_CRAWL_MAX_SUBLINKS]
            await asyncio.sleep(1.5)  # 稍作间隔，避免消息轰炸
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"🔎 曦曦发现了 {len(explore_urls)} 个值得探索的子页面，正在深入调查喵...",
            )

            # 并发抓取所有子链接
            sub_results = []
            for sub_url in explore_urls:
                _log.info(f"[深度爬虫] 抓取子链接: {sub_url}")
                sub_ok, sub_html = await web_crawler.fetch_page(sub_url)
                if sub_ok:
                    sub_info = web_crawler.extract_content(sub_html, sub_url)
                    sub_results.append(sub_info)
                    _log.info(f"[深度爬虫] 子链接抓取成功: {sub_info['title'][:30]}")
                else:
                    _log.warning(f"[深度爬虫] 子链接抓取失败: {sub_url} -> {sub_html}")

            if sub_results:
                # 构建综合分析 prompt
                deep_prompt = (
                    f"[深度网页分析任务 - 第二步：综合子页面信息]\n"
                    f"之前你分析了主页面 {page_info['title']}（{url}），现在我又帮你抓取了以下子页面的内容：\n\n"
                )
                for i, sub in enumerate(sub_results, 1):
                    deep_prompt += (
                        f"--- 子页面 {i}: {sub['title']} ---\n"
                        f"链接：{sub['url']}\n"
                        f"描述：{sub['description']}\n"
                        f"正文：{sub['content']}\n\n"
                    )
                deep_prompt += (
                    f"请根据主页面和这些子页面的信息，进行更深入的分析和总结：\n"
                    f"1. 综合所有信息给出更全面的见解\n"
                    f"2. 发现主页面可能没有展示的新信息\n"
                    f"3. 如果与用户之前的问题「{user_question}」相关，请补充回答\n"
                    f"4. 给出你自己的思考和延伸建议\n"
                )

                await asyncio.sleep(1)
                deep_reply = await ai_chat.chat(chat_id, deep_prompt, group_context=[])

                # 发送第二条消息（深度分析结果）
                msg2 = f"🔬 深度分析结果\n"
                msg2 += f"━━━━━━━━━━━━━━\n"
                msg2 += deep_reply
                await send_reply(ws, message_type, user_id, group_id, msg2)
                _log.info(f"[深度爬虫] 第二轮深度分析完成")

        # ===== 最后：如果回复很长，分段发送小贴士 =====
        await asyncio.sleep(1)
        tips_prompt = (
            f"[最后总结]\n"
            f"基于你刚才对 {page_info['title']} 的分析，请用1-2句话给出一个简短的总结评价或行动建议。"
            f"简洁有力，像朋友之间聊天一样自然。不需要重复之前说过的内容。"
        )
        tips_reply = await ai_chat.chat(chat_id, tips_prompt, group_context=[])
        if tips_reply and len(tips_reply.strip()) > 5:
            await send_reply(ws, message_type, user_id, group_id, f"💡 {tips_reply}")

        _log.info(f"[深度爬虫] 完整分析流程结束: {url}")

    except Exception as e:
        _log.error(f"[深度爬虫] 分析过程出错: {e}", exc_info=True)
        try:
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"深度分析过程中出了点小问题喵~已完成部分分析。",
            )
        except Exception:
            pass


async def process_message(ws, data):
    """处理单条消息事件（从优先级队列中取出后调用）"""
    message_type = data.get("message_type", "")
    user_id = data.get("user_id", 0)
    group_id = data.get("group_id", 0)
    raw_message = data.get("raw_message", "") or data.get("message", "")
    sender = data.get("sender", {})
    nickname = sender.get("nickname", "未知")

    content = extract_text(raw_message)

    # 检测消息中是否包含 QQ 表情（用于后续表情回复）
    msg_segments = data.get("message", "")
    _face_ids_in_msg = fun.extract_faces(msg_segments)

    # 检测消息中是否包含表情包 (mface)
    _mfaces_in_msg = fun.extract_mfaces(msg_segments)
    _douyin_url_from_segments = douyin.extract_douyin_url_from_segments(msg_segments)

    if (
        not content
        and not _face_ids_in_msg
        and not _mfaces_in_msg
        and not _douyin_url_from_segments
    ):
        return

    # ===== 表情包自动收集（无论是否@，群里发的表情包都收集） =====
    if _mfaces_in_msg:
        for mface in _mfaces_in_msg:
            fun.collect_sticker(mface)

    # ===== 封禁用户拦截（最高优先级，被ban的用户无法使用任何功能） =====
    if user_id in _banned_users:
        await send_reply(
            ws,
            message_type,
            user_id,
            group_id,
            "您已经被管理员banned喵，无法使用曦曦喵~",
        )
        return

    # ===== 抽奖交互拦截 (无需@直接回复) =====
    if message_type == "group":
        from handlers import lottery

        if lottery.is_creating(user_id, group_id):
            is_handled = await lottery.handle_creation_step(
                user_id,
                group_id,
                content,
                lambda m: send_reply(ws, message_type, user_id, group_id, m),
            )
            if is_handled:
                return

        if content == "参与抽奖" or content == "参加抽奖":
            join_msg = lottery.join_lottery(user_id, group_id)
            if join_msg:
                await send_reply(ws, message_type, user_id, group_id, join_msg)
            return

        if content == "提前开奖":
            if await lottery.try_early_draw(
                user_id,
                group_id,
                lambda m: send_reply(ws, message_type, user_id, group_id, m),
                lambda uid, m: send_api_request(
                    ws, "send_private_msg", {"user_id": uid, "message": m}
                ),
            ):
                return

    # ===== 发起人私聊存放抽奖奖励拦截 =====
    if message_type == "private":
        from handlers import lottery

        is_handled = await lottery.handle_pm_command(
            user_id,
            content,
            lambda m: send_api_request(
                ws, "send_private_msg", {"user_id": user_id, "message": m}
            ),
        )
        if is_handled:
            return

    # ===== 选择等待状态（点歌/GitHub） =====
    user_key = f"{message_type}_{group_id}_{user_id}"

    # 选歌状态
    select_songs = music.get_waiting(user_key)
    if select_songs is not None:
        if content.isdigit():
            idx = int(content)
            if 1 <= idx <= len(select_songs):
                song = select_songs[idx - 1]
                music.clear_waiting(user_key)
                share_msg = music.build_music_share(song)
                await send_reply(ws, message_type, user_id, group_id, share_msg)
                _log.info(f"[点歌] 选择: {song['name']} - {song['artist']}")
                return
            else:
                music.clear_waiting(user_key)
                await send_reply(
                    ws, message_type, user_id, group_id, "序号不对哦，点歌已取消喵~"
                )
                return
        else:
            music.clear_waiting(user_key)

    # GitHub 选择状态
    select_repos = github.get_waiting(user_key)
    if select_repos is not None:
        if content.isdigit():
            idx = int(content)
            if 1 <= idx <= len(select_repos):
                repo = select_repos[idx - 1]
                github.clear_waiting(user_key)
                detail_msg = github.build_repo_detail(repo)
                await send_reply(ws, message_type, user_id, group_id, detail_msg)
                _log.info(f"[GitHub] 选择: {repo['full_name']}")
                return
            else:
                github.clear_waiting(user_key)
                await send_reply(
                    ws, message_type, user_id, group_id, "序号不对哦，搜索已取消喵~"
                )
                return
        else:
            github.clear_waiting(user_key)

    # 广播喊话状态机（5分钟超时）
    hh_state = _hh_waiting.get(user_key)
    if hh_state:
        # 检查超时
        if _time_mod.time() > hh_state.get("expire", float("inf")):
            del _hh_waiting[user_key]
            # 超时静默清理，不打断用户
        else:
            # 取消操作
            if content in ("取消", "cancel", "算了"):
                del _hh_waiting[user_key]
                await send_reply(
                    ws, message_type, user_id, group_id, "已取消广播操作喵~"
                )
                return

        step = hh_state.get("step")
        all_groups = hh_state.get("groups", [])

        # 第一步：选择群
        if step == "select_group":
            indices = _parse_group_selection(content, len(all_groups))
            if indices is None:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    "输入格式不对喵~请输入序号，如：1,3,5 或 1-7 或 all\n回复「取消」可取消操作",
                )
                return

            selected = [all_groups[i] for i in indices]
            names = [
                f"{g.get('group_name', '?')}({g.get('group_id', '?')})"
                for g in selected[:5]
            ]
            preview = "、".join(names)
            if len(selected) > 5:
                preview += f" 等{len(selected)}个群"

            _hh_waiting[user_key] = {
                "step": "input_msg",
                "groups": all_groups,
                "selected": selected,
                "expire": _time_mod.time() + 300,
            }
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                f"✅ 已选择 {len(selected)} 个群：{preview}\n\n请输入要广播的消息内容：\n回复「取消」可取消操作",
            )
            return

        # 第二步：输入消息内容
        if step == "input_msg":
            selected = hh_state.get("selected", [])
            del _hh_waiting[user_key]

            if not content.strip():
                await send_reply(
                    ws, message_type, user_id, group_id, "消息内容不能为空喵~广播已取消"
                )
                return

            asyncio.create_task(
                _do_broadcast(
                    ws, message_type, user_id, group_id, nickname, content, selected
                )
            )
            return

    # 交互式删除 Staff 状态机（60秒超时）
    ds_state = _deletestaff_waiting.get(user_key)
    if ds_state:
        if _time_mod.time() > ds_state.get("expire", float("inf")):
            del _deletestaff_waiting[user_key]
        else:
            if content in ("取消", "cancel", "算了"):
                del _deletestaff_waiting[user_key]
                await send_reply(
                    ws, message_type, user_id, group_id, "已取消删除 Staff 操作喵~"
                )
                return

            if content.isdigit():
                idx = int(content)
                staff_list = ds_state.get("staff_list", [])
                if 1 <= idx <= len(staff_list):
                    target_qq = staff_list[idx - 1]
                    del _deletestaff_waiting[user_key]

                    if target_qq in _staff:
                        del _staff[target_qq]
                        _save_staff()
                        _staff_logged_in.discard(target_qq)
                        await send_reply(
                            ws,
                            message_type,
                            user_id,
                            group_id,
                            f"✅ 已移除 Staff QQ {target_qq} 喵~",
                        )
                        _log.info(
                            f"[STAFF] {nickname}({user_id}) 交互式移除了 Staff: {target_qq}"
                        )
                    else:
                        await send_reply(
                            ws,
                            message_type,
                            user_id,
                            group_id,
                            f"QQ {target_qq} 已不是 Staff 了喵~",
                        )
                    return
                else:
                    del _deletestaff_waiting[user_key]
                    await send_reply(
                        ws, message_type, user_id, group_id, "序号不对哦，操作已取消喵~"
                    )
                    return
            else:
                del _deletestaff_waiting[user_key]

    # 点歌输入歌名状态（60秒超时）
    music_ts = _music_waiting.get(user_key)
    if music_ts and (_time_mod.time() - music_ts < 60):
        del _music_waiting[user_key]
        await _do_search_music(ws, message_type, user_id, group_id, content, nickname)
        return
    elif music_ts:
        del _music_waiting[user_key]  # 超时清理

    # ===== 模糊指令确认 =====
    if await _handle_pending_command_hint(
        ws,
        message_type,
        user_id,
        group_id,
        user_key,
        content,
        nickname=nickname,
        raw_message=raw_message,
    ):
        return

    # ===== 抖音链接自动解析（优先于B站，避免抖音分享文案被B站正则误匹配） =====
    # 从纯文本中提取
    if content:
        douyin_url = douyin.extract_douyin_url(content)
    else:
        douyin_url = None
    # 从 JSON/XML 卡片消息中提取（QQ 内分享抖音时常见）
    if not douyin_url:
        douyin_url = _douyin_url_from_segments
    if douyin_url:
        _log.info(f"[抖音解析] 检测到: {douyin_url}")
        dy_info = await douyin.get_video_info(douyin_url)
        if dy_info:
            cover_url = dy_info.get("cover", "")
            msg = ""
            if cover_url:
                msg += f"[CQ:image,file={cover_url}]\n"
            msg += dy_info["text"]
            await send_reply(ws, message_type, user_id, group_id, msg)
            _log.info(f"[抖音解析] 成功")
        return

    # ===== B站链接自动解析（群内同一链接只解析一次） =====
    if content:
        bili_id = bilibili.extract_bilibili_id(content)
    else:
        bili_id = None
    if bili_id:
        # 群聊去重检查
        if message_type == "group" and group_id:
            now_ts = _time_mod.time()
            if group_id not in _bili_parsed:
                _bili_parsed[group_id] = {}

            # 清理过期记录
            expired_keys = [
                k
                for k, t in _bili_parsed[group_id].items()
                if now_ts - t > BILI_DEDUP_EXPIRE
            ]
            for k in expired_keys:
                del _bili_parsed[group_id][k]

            # 检查是否已解析过
            if bili_id in _bili_parsed[group_id]:
                _log.info(f"[B站解析] 跳过重复解析: 群{group_id} {bili_id}")
                return

            # 记录已解析
            _bili_parsed[group_id][bili_id] = now_ts

        _log.info(f"[B站解析] 检测到: {bili_id}")
        bili_result = await bilibili.get_video_info(bili_id)
        if bili_result:
            cover_url = bili_result.get("cover", "")
            msg = ""
            if cover_url:
                msg += f"[CQ:image,file={cover_url}]\n"
            msg += bili_result["text"]
            await send_reply(ws, message_type, user_id, group_id, msg)
            _log.info(f"[B站解析] 成功")
        return

    # ===== 斜杠指令 =====
    if content and content.startswith("/"):
        if await _maybe_suggest_command(
            ws, message_type, user_id, group_id, user_key, content
        ):
            _log.info(f"[模糊指令] {nickname}({user_id}) 输入: {content}")
            return
        if await _execute_command(
            ws, content, message_type, user_id, group_id, nickname, raw_message
        ):
            return

    # ===== 管理员私聊：Q qq号 [理由] 加好友 / 群 群号 [理由] 申请入群 =====
    if message_type == "private" and content and _is_admin_or_staff(user_id):
        parts = content.strip().split(None, 2)
        cmd_lower = parts[0].lower() if parts else ""

        if cmd_lower in ("q", "Q") and len(parts) >= 2 and parts[1].isdigit():
            target_id = int(parts[1])
            extra_msg = parts[2].strip() if len(parts) > 2 else "喵喵喵"

            success = False
            for action_name in ("add_friend", "set_friend_add_request"):
                resp = await send_api_request(
                    ws,
                    action_name,
                    {
                        "user_id": target_id,
                        "remark": extra_msg,
                        "comment": extra_msg,
                        "source": extra_msg,
                    },
                    timeout=10,
                )
                if resp.get("retcode") == 0:
                    success = True
                    break

            if success:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"已发送好友申请给 {target_id} 喵~（验证消息：{extra_msg}）",
                )
            else:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"已尝试添加好友 {target_id} 喵~（验证消息：{extra_msg}）\n"
                    f"注：Bot 可能无法主动加好友，如果对方发来好友申请会自动同意哦~",
                )
            _log.info(
                f"[加好友] {nickname}({user_id}) 添加好友 {target_id} 验证: {extra_msg}"
            )
            return

        if cmd_lower in ("群",) and len(parts) >= 2 and parts[1].isdigit():
            target_id = int(parts[1])
            extra_msg = parts[2].strip() if len(parts) > 2 else "喵喵喵"

            success = False
            for action_name in ("set_group_add_request", "join_group"):
                resp = await send_api_request(
                    ws,
                    action_name,
                    {
                        "group_id": target_id,
                        "reason": extra_msg,
                        "comment": extra_msg,
                    },
                    timeout=10,
                )
                if resp.get("retcode") == 0:
                    success = True
                    break

            if success:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"已申请加入群 {target_id} 喵~（申请理由：{extra_msg}）",
                )
            else:
                await send_reply(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    f"已尝试申请加入群 {target_id} 喵~（申请理由：{extra_msg}）\n"
                    f"注：Bot 可能无法主动申请入群，需要群主/管理员邀请哦~",
                )
            _log.info(
                f"[加群] {nickname}({user_id}) 申请加群 {target_id} 理由: {extra_msg}"
            )
            return

    # 群聊：需要 @ 或前缀才回复
    if message_type == "group":
        raw_msg = data.get("message", "")
        at_me = is_at_me(raw_msg)
        has_prefix = content.startswith(GROUP_TRIGGER) if content else False

        if not at_me and not has_prefix:
            return

        if has_prefix:
            content = content[len(GROUP_TRIGGER) :].strip()

        if not content and not _face_ids_in_msg and not _mfaces_in_msg:
            content = "你好"

    # 统一处理：指令 -> 关键词 -> 表情包回复 -> 表情回复 -> AI
    handled = False

    # 1. 内置指令
    if not handled and content:
        handled = await _execute_command(
            ws, content, message_type, user_id, group_id, nickname, raw_message
        )

    # 2. 关键词回复
    if not handled and content:
        reply_text = handler.get_reply(content)
        if reply_text:
            await send_reply(ws, message_type, user_id, group_id, reply_text)
            _log.info(f"[关键词回复] -> {reply_text[:50]}")
            handled = True

    # 2.3 表情包回复（检测消息中的 mface 表情包并回复）
    if not handled and _mfaces_in_msg:
        mface = _mfaces_in_msg[0]
        sticker_reply_text = fun.get_sticker_reply(mface)
        if sticker_reply_text:
            # 回复文字 + 随机附带一个已收集的表情包
            reply_msg = sticker_reply_text
            random_sticker = fun.find_sticker_by_keyword(mface.get("summary", ""))
            if not random_sticker:
                random_sticker = fun.get_random_sticker()
            if random_sticker:
                cq = fun.build_sticker_cq(random_sticker)
                if cq:
                    reply_msg += "\n" + cq
            await send_reply(ws, message_type, user_id, group_id, reply_msg)
            _log.info(
                f"[表情包回复] summary={mface.get('summary', '?')} -> {sticker_reply_text[:30]}"
            )
            handled = True

    # 2.5 表情回复（检测消息中的 QQ 表情并回复）
    if not handled and _face_ids_in_msg:
        face_reply = fun.get_face_reply(_face_ids_in_msg)
        if face_reply:
            await send_reply(ws, message_type, user_id, group_id, face_reply)
            _log.info(f"[表情回复] face_id={_face_ids_in_msg[0]} -> {face_reply[:30]}")
            handled = True

    # 3. 抽奖发起
    if not handled and content and content == "抽奖" and message_type == "group":
        from handlers import lottery

        start_msg = await lottery.start_lottery_creation(user_id, group_id)
        await send_reply(ws, message_type, user_id, group_id, start_msg)
        handled = True

    # 4. AI 对话（含网页爬虫：如果消息中包含URL，先抓取网页内容再喂给AI深度分析）
    if not handled:
        # 如果用户只发了表情包没有文字，给 AI 一个上下文提示
        ai_content = content
        if not ai_content and _mfaces_in_msg:
            summaries = [m.get("summary", "表情包") for m in _mfaces_in_msg]
            ai_content = f"（用户发送了表情包：{'、'.join(summaries)}）"
        elif not ai_content:
            ai_content = "你好"

        chat_id = f"g{group_id}_{user_id}" if message_type == "group" else str(user_id)

        # 检测消息中是否包含URL，如果有则启动深度分析流程
        detected_url = web_crawler.extract_url(ai_content) if ai_content else None
        if detected_url:
            _log.info(f"[爬虫+AI] 检测到URL: {detected_url}")
            await send_reply(
                ws,
                message_type,
                user_id,
                group_id,
                "🔍 检测到链接，正在抓取并深度分析喵...",
            )

            # 先发送网页截图
            screenshot_url = (
                f"https://image.thum.io/get/width/1280/crop/800/{detected_url}"
            )
            await send_reply(
                ws, message_type, user_id, group_id, f"[CQ:image,file={screenshot_url}]"
            )
            _log.info(f"[网页截图] 已发送: {detected_url}")

            # 启动后台深度分析任务（多步骤、多消息）
            asyncio.create_task(
                _deep_crawl_analyze(
                    ws,
                    message_type,
                    user_id,
                    group_id,
                    chat_id,
                    detected_url,
                    ai_content,
                )
            )
        else:
            _log.info(f"[AI请求中] chat_id={chat_id}")
            # 群聊被@时才读取群聊缓存给AI提供上下文
            group_ctx = (
                _group_chat_cache.get(group_id, []) if message_type == "group" else []
            )
            reply_text = await ai_chat.chat(
                chat_id, ai_content, group_context=group_ctx
            )

            # 后处理：将 AI 回复中的 [sticker:xxx] 替换为实际表情包 CQ 码
            reply_text = fun.process_ai_stickers(reply_text)

            # 支持多段回复：AI 用 [---SPLIT---] 分隔时，分多条消息发送
            segments = [
                s.strip() for s in reply_text.split("[---SPLIT---]") if s.strip()
            ]
            if len(segments) > 1:
                for i, seg in enumerate(segments):
                    await send_reply(ws, message_type, user_id, group_id, seg)
                    _log.info(f"[AI回复] 分段 {i + 1}/{len(segments)} -> {seg[:60]}")
                    if i < len(segments) - 1:
                        await asyncio.sleep(1.5)  # 分段间隔，模拟自然打字
            else:
                await send_reply(ws, message_type, user_id, group_id, reply_text)
                _log.info(f"[AI回复] -> {reply_text[:80]}")


# 并发消费者数量：与当前 API 的 10 并发上限对齐
MSG_WORKERS = 10


# Worker 处理单条消息的最大超时时间（秒），防止卡死
WORKER_TIMEOUT = 120

# WebSocket 稳定性参数：适当放宽 ping/pong 与接收缓冲，减少误判断连
WS_OPEN_TIMEOUT = 20
WS_PING_INTERVAL = 30
WS_PING_TIMEOUT = 60
WS_CLOSE_TIMEOUT = 10
WS_MAX_QUEUE = 256


async def message_consumer(ws, worker_id: int):
    """消息消费者 worker：按优先级处理消息，VIP 的消息永远排在最前面"""
    while True:
        try:
            # 检查连接是否已关闭，如果已关闭则退出当前 worker，防止泄露的老 worker 偷消息
            if _is_ws_closed(ws):
                _log.info(f"[Worker-{worker_id}] WebSocket已关闭，当前 Worker 退出")
                break

            priority, _, data = await _msg_queue.get()

            # 拿到消息后再检查一次
            if _is_ws_closed(ws):
                # 连接已断开，把消息放回队首（因为使用了 PriorityQueue，直接再 put 进去即可）
                _msg_queue.put_nowait(
                    (
                        priority,
                        _get_running_loop().time(),
                        data,
                    )
                )
                break

            user_id = data.get("user_id", 0)
            tag = "⭐VIP" if user_id == VIP_QQ else "普通"
            _log.info(
                f"[Worker-{worker_id}] 处理{tag}消息 (队列剩余: {_msg_queue.qsize()})"
            )
            try:
                await asyncio.wait_for(
                    process_message(ws, data), timeout=WORKER_TIMEOUT
                )
            except asyncio.TimeoutError:
                _log.error(
                    f"[Worker-{worker_id}] 处理超时 ({WORKER_TIMEOUT}s)，强制跳过"
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            _log.error(f"[Worker-{worker_id}] 出错: {e}", exc_info=False)


async def main():
    """主函数"""
    headers = {}
    if WS_TOKEN:
        headers["Authorization"] = f"Bearer {WS_TOKEN}"

    _log.info("=" * 50)
    _log.info("QQ 机器人「曦曦」启动中...")
    _log.info(f"连接地址: {WS_URL}")
    _log.info(f"已加载 {len(config.get('replies', []))} 条回复规则")
    _log.info(f"AI 模型: {ai_config.get('model', '未配置')}")
    _log.info(
        f"功能: 签到 | 运势 | 点歌 | NFA | 4399 | 163 | B站/抖音/网页解析 | 布吉岛 | AI对话"
    )
    _log.info("=" * 50)

    while True:
        try:
            async with websockets.connect(
                WS_URL,
                additional_headers=headers if headers else None,
                max_size=10 * 1024 * 1024,
                max_queue=WS_MAX_QUEUE,
                open_timeout=WS_OPEN_TIMEOUT,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_PING_TIMEOUT,
                close_timeout=WS_CLOSE_TIMEOUT,
            ) as ws:
                _log.info("已成功连接到 NapCatQQ！曦曦上线！")
                connection_tasks: list[asyncio.Task] = []

                # ===== 重连时清理陈旧状态 =====
                _music_waiting.clear()
                _hh_waiting.clear()
                _deletestaff_waiting.clear()
                _staff_logged_in.clear()
                # 取消所有待处理的 API Future
                onebot.cancel_pending()
                # 清空消息队列中的旧消息
                while not _msg_queue.empty():
                    try:
                        _msg_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                _log.info("[重连] 已清理陈旧状态缓存")

                # 检查重启标记，通知触发重启的用户
                await _check_restart_flag(ws)

                # 启动布吉岛更新监控后台任务
                bjd_task = asyncio.create_task(bjd_check_loop(ws))
                connection_tasks.append(bjd_task)
                # 启动抽奖定时监测后台任务
                lottery_task = asyncio.create_task(lottery_check_loop(ws))
                connection_tasks.append(lottery_task)
                # 启动定时缓存清理任务（每10分钟）
                cleanup_task = asyncio.create_task(_cleanup_caches(ws))
                connection_tasks.append(cleanup_task)
                # 启动消息消费者（10 个并发 worker，可同时回复 10 个人）
                for i in range(MSG_WORKERS):
                    connection_tasks.append(
                        asyncio.create_task(message_consumer(ws, i + 1))
                    )
                _log.info(f"已启动 {MSG_WORKERS} 个消息处理 Worker")

                try:
                    msg_count = 0
                    async for raw in ws:
                        msg_count += 1
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        data = onebot.normalize_incoming_payload(data)
                        if not data:
                            continue

                        post_type = data.get("post_type", "")

                        # 忽略元事件
                        if post_type == "meta_event":
                            continue

                        # ========== 入群欢迎 + 撤回提醒 ==========
                        if post_type == "notice":
                            notice_type = data.get("notice_type", "")

                            if notice_type == "group_increase":
                                gid = data.get("group_id", 0)
                                new_user = data.get("user_id", 0)
                                if new_user != BOT_QQ:
                                    welcome = fun.get_welcome_msg(
                                        f"[CQ:at,qq={new_user}]"
                                    )
                                    await _send_raw(ws, "group", 0, gid, welcome)
                                    _log.info(f"[入群欢迎] 群{gid} 新成员{new_user}")

                            elif notice_type == "group_recall" and NOTIFY_QQ:
                                gid = data.get("group_id", 0)
                                user_id_recall = data.get("user_id", 0)
                                msg_id = str(data.get("message_id", ""))

                                cached = _msg_cache.get(msg_id)
                                if not cached:
                                    cached = _lookup_msg_from_files(msg_id)
                                if cached:
                                    recall_nickname = cached.get(
                                        "nickname", str(user_id_recall)
                                    )
                                    recall_content = cached.get("content", "[无法获取]")
                                else:
                                    recall_nickname = str(user_id_recall)
                                    recall_content = "[消息未缓存]"

                                notify_text = (
                                    f"撤回提醒\n"
                                    f"━━━━━━━━━━━━━━\n"
                                    f"群号：{gid}\n"
                                    f"撤回人：{recall_nickname}({user_id_recall})\n"
                                    f"内容：{recall_content}"
                                )
                                recall_images = (
                                    cached.get("images", []) if cached else []
                                )
                                if recall_images:
                                    notify_text += "\n━━━ 撤回图片 ━━━"
                                await _send_raw(
                                    ws, "private", NOTIFY_QQ, 0, notify_text
                                )
                                for img_url in recall_images:
                                    await _send_raw(
                                        ws,
                                        "private",
                                        NOTIFY_QQ,
                                        0,
                                        f"[CQ:image,file={img_url}]",
                                    )
                                _log.info(
                                    f"[撤回提醒] 群{gid} {recall_nickname} 撤回: {recall_content[:50]} 图片:{len(recall_images)}张"
                                )

                            elif notice_type == "friend_recall" and NOTIFY_QQ:
                                user_id_recall = data.get("user_id", 0)
                                msg_id = str(data.get("message_id", ""))

                                cached = _msg_cache.get(msg_id)
                                if not cached:
                                    cached = _lookup_msg_from_files(msg_id)
                                if cached:
                                    recall_nickname = cached.get(
                                        "nickname", str(user_id_recall)
                                    )
                                    recall_content = cached.get("content", "[无法获取]")
                                else:
                                    recall_nickname = str(user_id_recall)
                                    recall_content = "[消息未缓存]"

                                notify_text = (
                                    f"撤回提醒\n"
                                    f"━━━━━━━━━━━━━━\n"
                                    f"来源：私聊\n"
                                    f"撤回人：{recall_nickname}({user_id_recall})\n"
                                    f"内容：{recall_content}"
                                )
                                recall_images = (
                                    cached.get("images", []) if cached else []
                                )
                                if recall_images:
                                    notify_text += "\n━━━ 撤回图片 ━━━"
                                await _send_raw(
                                    ws, "private", NOTIFY_QQ, 0, notify_text
                                )
                                for img_url in recall_images:
                                    await _send_raw(
                                        ws,
                                        "private",
                                        NOTIFY_QQ,
                                        0,
                                        f"[CQ:image,file={img_url}]",
                                    )
                                _log.info(
                                    f"[撤回提醒] 私聊 {recall_nickname} 撤回: {recall_content[:50]} 图片:{len(recall_images)}张"
                                )

                            continue

                        # ========== 请求事件（加群邀请/好友请求） ==========
                        if post_type == "request":
                            request_type = data.get("request_type", "")
                            sub_type = data.get("sub_type", "")

                            if request_type == "group" and sub_type == "invite":
                                flag = data.get("flag", "")
                                group_id_req = data.get("group_id", 0)
                                inviter = data.get("user_id", 0)

                                await send_api_request(
                                    ws,
                                    "set_group_add_request",
                                    {
                                        "flag": flag,
                                        "sub_type": "invite",
                                        "approve": True,
                                    },
                                    timeout=8,
                                )
                                _log.info(
                                    f"[进群邀请] 已同意加入群 {group_id_req}，邀请人 {inviter}"
                                )

                                await _send_raw(
                                    ws, "private", inviter, 0, "已经同意进群喵~"
                                )

                            elif request_type == "friend":
                                flag = data.get("flag", "")
                                req_user = data.get("user_id", 0)

                                await send_api_request(
                                    ws,
                                    "set_friend_add_request",
                                    {
                                        "flag": flag,
                                        "approve": True,
                                    },
                                    timeout=8,
                                )
                                _log.info(f"[好友请求] 已同意 {req_user} 的好友请求")

                            continue

                        # ========== 消息事件 ==========
                        if post_type == "message":
                            user_id = data.get("user_id", 0)
                            self_id = data.get("self_id", 0)
                            raw_message = data.get("raw_message", "") or data.get(
                                "message", ""
                            )
                            sender = data.get("sender", {})
                            nickname = sender.get("nickname", "未知")
                            msg_id = str(data.get("message_id", ""))
                            group_id = data.get("group_id", 0)
                            content = extract_text(raw_message)

                            if msg_id:
                                cache_content = content or extract_text(raw_message)
                                if len(cache_content) > 200:
                                    cache_content = cache_content[:200] + "..."
                                raw_str = (
                                    raw_message
                                    if isinstance(raw_message, str)
                                    else str(raw_message)
                                )
                                img_urls = re.findall(
                                    r"\[CQ:image,[^\]]*url=([^\],\]]+)", raw_str
                                )
                                _msg_cache[msg_id] = {
                                    "nickname": nickname,
                                    "user_id": user_id,
                                    "content": cache_content,
                                    "group_id": group_id,
                                    "images": img_urls,
                                    "time": datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                }
                                # 缓存满 300 条时导出到文件并清空
                                if len(_msg_cache) >= MAX_CACHE:
                                    _export_msg_cache()

                            if user_id == self_id:
                                continue
                            if BOT_QQ and user_id == BOT_QQ:
                                continue

                            msg_segments = data.get("message", "")
                            has_mface = bool(fun.extract_mfaces(msg_segments))
                            has_face = bool(fun.extract_faces(msg_segments))

                            if not content and not has_mface and not has_face:
                                continue

                            dedup_key = f"{msg_id}_{user_id}_{content[:20] if content else 'sticker'}"
                            if dedup_key in _processed_msgs:
                                continue
                            _processed_msgs[dedup_key] = None
                            while len(_processed_msgs) > MAX_PROCESSED:
                                _processed_msgs.popitem(last=False)

                            tag = (
                                f"群聊 {group_id}"
                                if data.get("message_type") == "group"
                                else "私聊"
                            )
                            _log.info(
                                f"[{tag}] {nickname}({user_id}): {content} [msg_id={msg_id}]"
                            )

                            if data.get("message_type") == "group" and group_id:
                                cache_text = (
                                    content[:120] if len(content) > 120 else content
                                )
                                if group_id not in _group_chat_cache:
                                    _group_chat_cache[group_id] = []
                                _group_chat_cache[group_id].append(
                                    {"nickname": nickname, "content": cache_text}
                                )
                                if len(_group_chat_cache[group_id]) > MAX_GROUP_CONTEXT:
                                    _group_chat_cache[group_id] = _group_chat_cache[
                                        group_id
                                    ][-MAX_GROUP_CONTEXT:]
                                _group_chat_cache.move_to_end(group_id)
                                while len(_group_chat_cache) > MAX_GROUP_CACHE_GROUPS:
                                    _group_chat_cache.popitem(last=False)

                            global _msg_counter
                            priority = 0 if user_id == VIP_QQ else 1
                            _msg_counter += 1
                            if _msg_queue.full():
                                _log.warning(
                                    f"[队列满] 消息丢弃: {nickname}({user_id})"
                                )
                                continue
                            await _msg_queue.put((priority, _msg_counter, data))
                            continue

                        # API 响应（兼容 retcode/status 两种风格）
                        if "retcode" in data or ("echo" in data and "status" in data):
                            onebot.handle_api_response(data)
                            continue

                        _log.debug(f"[WS] 收到未识别数据包，已忽略: {str(data)[:200]}")
                finally:
                    onebot.resolve_pending({"retcode": -1, "status": "disconnected"})
                    for task in connection_tasks:
                        if not task.done():
                            task.cancel()
                    if connection_tasks:
                        await asyncio.gather(*connection_tasks, return_exceptions=True)

        except (ConnectionRefusedError, OSError) as e:
            _log.warning(f"连接失败: {e}")
            _log.info("5 秒后重新连接...")
            await asyncio.sleep(5)

        except websockets.exceptions.ConnectionClosed as e:
            _log.warning(f"连接断开: {e}")
            _log.info("3 秒后重新连接...")
            await asyncio.sleep(3)

        except Exception as e:
            _log.error(f"未知错误: {e}", exc_info=True)
            _log.info("5 秒后重新连接...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
