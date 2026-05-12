"""
布吉岛更新监控模块
定时检测版本更新，支持定时播报和实时更新推送
"""

import json
import asyncio
import logging

_log = logging.getLogger("QQBot")

API_RESOURCES = "https://archive.freecookie.studio/api/resources"
API_LAUNCHER = "https://archive.freecookie.studio/api/launcher"

# 记录上次已知的版本
_last_known_version: str = ""


async def get_latest_version() -> dict | None:
    """
    获取布吉岛最新版本信息
    返回 {version, name, date, launcher_version} 或 None
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--noproxy", "*", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0",
            API_RESOURCES,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return None

        data = json.loads(raw)
        if not data or not isinstance(data, list):
            return None

        # 第一个就是最新的
        latest = data[0]
        meta = latest.get("meta", {})

        # 获取 launcher 版本
        launcher_version = ""
        try:
            proc2 = await asyncio.create_subprocess_exec(
                "curl", "-s", "--noproxy", "*", "--max-time", "10",
                "-H", "User-Agent: Mozilla/5.0",
                API_LAUNCHER,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            raw2 = stdout2.decode("utf-8", errors="replace").strip()
            if raw2:
                launcher_data = json.loads(raw2)
                launcher_version = launcher_data.get("version", "")
        except Exception:
            pass

        return {
            "version": meta.get("item_version", "未知"),
            "name": meta.get("name", "布吉岛"),
            "res_name": latest.get("res_name", ""),
            "date": latest.get("created_at", "")[:10],
            "online": meta.get("online_count", "0"),
            "downloads": meta.get("download_num", 0),
            "launcher_version": launcher_version,
        }

    except Exception as e:
        _log.warning(f"获取布吉岛版本失败: {e}")
        return None


def build_update_msg(info: dict, is_update: bool) -> str:
    """构建播报消息"""
    if is_update:
        msg = f"布吉岛更新播报\n"
        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"布吉岛已更新喵！\n"
        msg += f"更新版本：v{info['version']}\n"
    else:
        msg = f"布吉岛版本播报\n"
        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"目前布吉岛并未更新喵~\n"
        msg += f"当前版本：v{info['version']}\n"

    msg += f"资源包：{info['res_name']}\n"
    msg += f"更新日期：{info['date']}\n"
    if info.get("launcher_version"):
        msg += f"启动器版本：{info['launcher_version']}\n"
    msg += f"━━━━━━━━━━━━━━"

    return msg


def get_last_version() -> str:
    global _last_known_version
    return _last_known_version


def set_last_version(version: str):
    global _last_known_version
    _last_known_version = version
