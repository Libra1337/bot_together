"""
跨 Bot 共享冷却/封禁状态
两个 bot 通过同一个 JSON 文件同步 NFA 和 163 的冷却、频率、封禁信息
"""

import json
import os
import time
import logging

_log = logging.getLogger("QQBot")

SHARED_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "cooldowns.json"
)

# 内存缓存 + 文件同步
_cache: dict = {}
_last_load_ts: float = 0
_RELOAD_INTERVAL = 1.0  # 每次检查前最多 1 秒读一次文件


def _load():
    """从共享文件加载状态"""
    global _cache, _last_load_ts
    now = time.time()
    if now - _last_load_ts < _RELOAD_INTERVAL:
        return
    _last_load_ts = now
    try:
        if os.path.exists(SHARED_FILE):
            with open(SHARED_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    except Exception:
        pass


def _save():
    """把状态写回共享文件"""
    try:
        os.makedirs(os.path.dirname(SHARED_FILE), exist_ok=True)
        with open(SHARED_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception as e:
        _log.warning(f"[共享冷却] 写文件失败: {e}")


def _section(feature: str) -> dict:
    """获取某个功能的子 dict"""
    if feature not in _cache:
        _cache[feature] = {}
    return _cache[feature]


# ========== 通用接口 ==========


def is_banned(feature: str, user_id: int) -> tuple[bool, int, int]:
    """
    检查用户是否被封禁
    返回 (是否封禁, 剩余小时, 剩余分钟)
    """
    _load()
    bans = _section(f"{feature}_ban")
    ban_until = bans.get(str(user_id), 0)
    now = time.time()
    if ban_until > now:
        remain = ban_until - now
        return True, int(remain / 3600), int(remain % 3600 / 60)
    elif ban_until:
        del bans[str(user_id)]
        _save()
    return False, 0, 0


def check_cooldown(
    feature: str, user_id: int, cooldown_seconds: int
) -> tuple[bool, int]:
    """
    检查冷却是否已过
    返回 (是否在冷却中, 剩余秒数)
    """
    _load()
    cds = _section(f"{feature}_cd")
    last = cds.get(str(user_id), 0)
    elapsed = time.time() - last
    if elapsed < cooldown_seconds:
        return True, int(cooldown_seconds - elapsed)
    return False, 0


def check_hour_limit(
    feature: str, user_id: int, limit: int, ban_duration: int
) -> tuple[bool, int]:
    """
    检查一小时内是否超限，超限则自动封禁
    返回 (是否超限, 本小时已获取次数)
    """
    _load()
    logs = _section(f"{feature}_log")
    uid = str(user_id)
    now = time.time()
    hour_log = [ts for ts in (logs.get(uid) or []) if now - ts < 3600]

    if len(hour_log) >= limit:
        # 触发封禁
        bans = _section(f"{feature}_ban")
        bans[uid] = now + ban_duration
        logs.pop(uid, None)
        _save()
        return True, len(hour_log)

    logs[uid] = hour_log
    return False, len(hour_log)


def record_usage(feature: str, user_id: int):
    """
    记录一次成功获取：写入冷却 + 频率记录
    必须在 check 通过之后、调 API 之前调用（防并发）
    """
    _load()
    uid = str(user_id)
    now = time.time()

    # 写冷却
    cds = _section(f"{feature}_cd")
    cds[uid] = now

    # 写频率
    logs = _section(f"{feature}_log")
    hour_log = [ts for ts in (logs.get(uid) or []) if now - ts < 3600]
    hour_log.append(now)
    logs[uid] = hour_log

    _save()
