"""
Hypixel Ban Tracker 模块
查询 Hypixel 服务器的封禁统计数据
"""

import asyncio
import json
import logging

_log = logging.getLogger("QQBot")

PUNISH_API = "https://bantracker-api.xcnya.cn/"


def _fmt(n) -> str:
    """格式化数字"""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n:,}"


async def _fetch_data() -> dict | None:
    """请求 API 获取封禁统计数据"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            PUNISH_API,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return None

        data = json.loads(raw)
        if "staff" not in data or "watchdog" not in data:
            return None

        return data
    except Exception as e:
        _log.error(f"Hypixel API 请求失败: {e}")
        return None


async def get_ban_stats() -> str:
    """获取 Hypixel 封禁统计数据"""
    data = await _fetch_data()
    if data is None:
        return "Hypixel 封禁数据获取失败了喵，请稍后再试~"

    wd = data.get("watchdog", {})
    st = data.get("staff", {})

    watchdog_total = wd.get("total", 0)
    watchdog_daily = wd.get("last_day", 0)
    watchdog_last_min = wd.get("last_minute", 0)
    staff_total = st.get("total", 0)
    staff_daily = st.get("last_day", 0)
    staff_last_min = st.get("last_minute", 0)

    text = f"Hypixel 封禁统计\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"Watchdog 反作弊\n"
    text += f"  总封禁：{_fmt(watchdog_total)}\n"
    text += f"  今日封禁：{_fmt(watchdog_daily)}\n"
    text += f"  最近1分钟：{_fmt(watchdog_last_min)}\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"Staff 人工封禁\n"
    text += f"  总封禁：{_fmt(staff_total)}\n"
    text += f"  今日封禁：{_fmt(staff_daily)}\n"
    text += f"  最近1分钟：{_fmt(staff_last_min)}\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"合计封禁：{_fmt(watchdog_total + staff_total)}"
    return text
