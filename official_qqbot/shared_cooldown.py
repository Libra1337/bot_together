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
RESTRICT_WINDOWS = {
    "min": 60,
    "hour": 3600,
    "day": 86400,
    "month": 30 * 86400,
    "quarter": 90 * 86400,
    "year": 365 * 86400,
}
RESTRICT_FEATURES = {"163", "4399", "nfa"}
RESTRICT_STATS_WINDOWS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "month": 30 * 86400,
    "year": 365 * 86400,
}
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
        data_dir = os.path.dirname(SHARED_FILE)
        os.makedirs(data_dir, exist_ok=True)
        tmp_file = f"{SHARED_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, SHARED_FILE)
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


def set_restrict_rule(feature: str, limit: int, unit: str) -> None:
    feature = str(feature).strip().lower()
    unit = str(unit).strip().lower()
    if feature not in RESTRICT_FEATURES:
        raise ValueError("invalid feature")
    if limit <= 0:
        raise ValueError("invalid limit")
    if unit not in RESTRICT_WINDOWS:
        raise ValueError("invalid unit")

    _load()
    rules = _section("restrict_rules")
    rules[feature] = {
        "limit": int(limit),
        "unit": unit,
        "window": RESTRICT_WINDOWS[unit],
    }
    _save()


def get_restrict_rule(feature: str) -> dict | None:
    _load()
    rule = _section("restrict_rules").get(str(feature).strip().lower())
    return rule if isinstance(rule, dict) else None


def _recent_restrict_usage(feature: str, user_id, now: float, window: int) -> list[float]:
    logs = _section("restrict_log")
    feature_logs = logs.setdefault(feature, {})
    recent = [
        float(ts)
        for ts in (feature_logs.get(str(user_id)) or [])
        if now - float(ts) < window
    ]
    feature_logs[str(user_id)] = recent
    return recent


def get_restrict_status(feature: str, user_id) -> dict:
    feature = str(feature).strip().lower()
    rule = get_restrict_rule(feature)
    if not rule:
        return {
            "blocked": False,
            "count": 0,
            "limit": 0,
            "window": 0,
            "reset_after": 0,
        }

    limit = int(rule.get("limit", 0) or 0)
    window = int(rule.get("window", 0) or 0)
    if limit <= 0 or window <= 0:
        return {
            "blocked": False,
            "count": 0,
            "limit": 0,
            "window": 0,
            "reset_after": 0,
        }

    _load()
    now = time.time()
    recent = _recent_restrict_usage(feature, user_id, now, window)
    _save()

    reset_after = 0
    if recent:
        reset_after = max(0, int(window - (now - min(recent))))

    return {
        "blocked": len(recent) >= limit,
        "count": len(recent),
        "limit": limit,
        "window": window,
        "reset_after": reset_after,
    }


def check_restrict_limit(feature: str, user_id) -> tuple[bool, int, int, int]:
    status = get_restrict_status(feature, user_id)
    return (
        bool(status["blocked"]),
        int(status["count"]),
        int(status["limit"]),
        int(status["window"]),
    )


def record_restrict_usage(feature: str, user_id) -> None:
    feature = str(feature).strip().lower()
    if not get_restrict_rule(feature):
        return

    _load()
    uid = str(user_id)
    now = time.time()
    logs = _section("restrict_log")
    feature_logs = logs.setdefault(feature, {})
    recent = list(feature_logs.get(uid) or [])
    recent.append(now)
    feature_logs[uid] = recent
    _save()


def reset_restrict_usage() -> None:
    """清空所有资源获取限制记录，保留 /restrict 规则。"""
    _load()
    _cache["restrict_log"] = {}
    _save()


def get_restrict_usage_stats() -> list[dict]:
    _load()
    now = time.time()
    rules = _section("restrict_rules")
    logs = _section("restrict_log")
    items = []
    for feature in sorted(RESTRICT_FEATURES):
        rule = rules.get(feature) if isinstance(rules, dict) else None
        if not isinstance(rule, dict):
            continue
        feature_logs = logs.get(feature, {}) if isinstance(logs, dict) else {}
        all_timestamps = [
            float(ts)
            for user_logs in feature_logs.values()
            for ts in (user_logs or [])
        ]
        counts = {
            key: sum(1 for ts in all_timestamps if now - ts <= seconds)
            for key, seconds in RESTRICT_STATS_WINDOWS.items()
        }
        items.append(
            {
                "resource": feature,
                "limit_count": int(rule.get("limit", 0) or 0),
                "window_unit": str(rule.get("unit", "") or ""),
                "window_seconds": int(rule.get("window", 0) or 0),
                "counts": counts,
            }
        )
    return items
