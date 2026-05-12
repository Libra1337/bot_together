"""
NFA Token 获取模块
流程：登录管理API获取key -> 用key请求NFA接口获取JWT token
"""

import json
import asyncio
import logging
import time as _time_mod

_log = logging.getLogger("QQBot")

MANAGER_API = "http://newqwqovoawa.shirochisa.tech:3000"
NFA_API = "http://newqwqovoawa.shirochisa.tech:3000/api/nfa/get"
NFA_STATS_API = "http://newqwqovoawa.shirochisa.tech:3000/api/nfa/stats"

_LOGIN_CACHE_SECONDS = 900
_LOGIN_LIMIT_BACKOFF_SECONDS = 120
_cached_key = ""
_cached_key_username = ""
_cached_key_until = 0.0
_login_blocked_until = 0.0
_last_login_error = ""
_login_lock = asyncio.Lock()


def _login_error_message(data: dict) -> str:
    return data.get("message") or data.get("msg") or data.get("error") or "未知错误"


async def _get_current_key(username: str, password: str) -> tuple[bool, str, str]:
    global _cached_key, _cached_key_username, _cached_key_until
    global _login_blocked_until, _last_login_error

    now = _time_mod.time()
    if _cached_key and _cached_key_username == username and now < _cached_key_until:
        return True, _cached_key, ""

    async with _login_lock:
        now = _time_mod.time()
        if _cached_key and _cached_key_username == username and now < _cached_key_until:
            return True, _cached_key, ""

        if now < _login_blocked_until:
            remain = int(_login_blocked_until - now)
            msg = _last_login_error or "该账号登录尝试过于频繁，请稍后再试"
            return False, "", f"NFA 登录失败喵：{msg}（约 {remain} 秒后再试）"

        login_data = json.dumps({"username": username, "password": password})
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "--noproxy",
            "*",
            "--max-time",
            "10",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            login_data,
            f"{MANAGER_API}/api/login",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        raw = stdout.decode("utf-8", errors="replace").strip()

        if not raw:
            return False, "", "NFA 管理服务暂时无法连接喵~"

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return False, "", "NFA 登录接口返回异常喵~"

        if not data.get("success"):
            err_msg = _login_error_message(data)
            if "频繁" in err_msg or "too frequent" in err_msg.lower():
                _last_login_error = err_msg
                _login_blocked_until = _time_mod.time() + _LOGIN_LIMIT_BACKOFF_SECONDS
            return False, "", f"NFA 登录失败喵：{err_msg}"

        current_key = data.get("user", {}).get("currentKey", "") or data.get(
            "currentKey", ""
        )
        if not current_key:
            return False, "", "NFA 登录成功但没有找到 key 喵~"

        _cached_key = current_key
        _cached_key_username = username
        _cached_key_until = _time_mod.time() + _LOGIN_CACHE_SECONDS
        _login_blocked_until = 0.0
        _last_login_error = ""
        _log.info(f"[NFA] 登录成功，key: ...{current_key[-6:]}")
        return True, current_key, ""


async def get_nfa_token(username: str, password: str) -> str:
    """
    获取NFA JWT token
    1. 登录管理API获取currentKey
    2. 用key请求NFA接口获取JWT token
    """
    try:
        # Step 1: 登录获取 currentKey（进程内缓存，避免触发登录频率限制）
        ok, current_key, err = await _get_current_key(username, password)
        if not ok:
            return err

        # Step 2: 用 key 请求 NFA 接口获取 JWT token（SSE格式，实时读取）
        nfa_url = f"{NFA_API}?key={current_key}"

        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "-N",
            "--noproxy",
            "*",
            "--max-time",
            "90",
            "-H",
            "User-Agent: Mozilla/5.0",
            nfa_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 实时逐行读取 SSE 流，收到 success 立刻返回
        last_message = ""
        line_count = 0
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=90)
                if not line:
                    _log.info(f"[NFA] SSE EOF，共读取 {line_count} 行")
                    break  # EOF

                line = line.decode("utf-8", errors="replace").strip()
                line_count += 1
                _log.info(f"[NFA] 第{line_count}行: {line[:200]}")
                if not line.startswith("data:"):
                    continue

                json_str = line[5:].strip()
                try:
                    sse_data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                status = sse_data.get("status", "")
                message = sse_data.get("message", "")
                last_message = message
                _log.info(f"[NFA] SSE status={status}, message={message}")

                if status == "success" and sse_data.get("data"):
                    nfa_data = sse_data["data"]
                    # 拿到结果，终止 curl
                    try:
                        proc.kill()
                    except Exception:
                        pass

                    username_nfa = nfa_data.get("u", "未知")
                    uuid = nfa_data.get("i", "未知")
                    token = nfa_data.get("t", "未知")

                    result = f"主人您的nfa来了喵~\n"
                    result += f"━━━━━━━━━━━━━━\n"
                    result += f"ID：{username_nfa}\n"
                    result += f"UUID：{uuid}\n"
                    result += f"Token：{token}"
                    return result

        except asyncio.TimeoutError:
            proc.kill()
            _log.warning("[NFA] SSE 读取超时")

        # 没有收到 success，读取 stderr 排查原因
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        try:
            stderr_data = await proc.stderr.read()
            stderr_text = (
                stderr_data.decode("utf-8", errors="replace").strip()
                if stderr_data
                else ""
            )
            _log.warning(
                f"[NFA] curl退出码={proc.returncode}, stderr={stderr_text[:300]}"
            )
        except Exception:
            pass
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        _log.warning(f"[NFA] 未获取到成功数据，last_message={last_message}")
        return f"NFA 获取失败喵：{last_message or '服务端未返回有效数据'}"

    except Exception as e:
        _log.error(f"NFA 获取失败: {e}")
        return "NFA 获取失败了喵，请稍后再试~"


async def get_nfa_stock(
    username: str = "admin", password: str = "zutomayo0."
) -> tuple[bool, int, str]:
    """
    查询 NFA 库存数量（通过登录获取 key，再调 /api/nfa/stats 读取 db_count）
    返回 (成功, 库存数量, 错误信息)
    """
    try:
        # Step 1: 登录获取 currentKey（进程内缓存，避免触发登录频率限制）
        ok, current_key, err = await _get_current_key(username, password)
        if not ok:
            return False, 0, err

        # Step 2: 用 key 请求 stats 接口获取库存
        stats_url = f"{NFA_STATS_API}?key={current_key}"

        proc2 = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "--noproxy",
            "*",
            "--max-time",
            "10",
            "-H",
            "User-Agent: Mozilla/5.0",
            stats_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout2, _ = await proc2.communicate()
        raw2 = stdout2.decode("utf-8", errors="replace").strip()

        if not raw2:
            return False, 0, "NFA 库存接口无响应喵~"

        stats = json.loads(raw2)
        db_count = stats.get("db_count", 0)
        _log.info(f"[NFA库存] 查询成功，db_count={db_count}")
        return True, int(db_count), ""

    except Exception as e:
        _log.error(f"[NFA库存] 查询失败: {e}")
        return False, 0, "NFA 库存查询失败了喵，请稍后再试~"
