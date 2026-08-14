"""
4399 Sauth 获取模块
支持多人并发获取（共享连接池 + 信号量限流）
"""

import json
import asyncio
import logging
import os
import re
import time

import httpx

_log = logging.getLogger("QQBot")

SAUTH_API = "https://cookie.meowow.org/api/accounts/sauth/quick"
ACCOUNT_163_API = "https://cookie.meowow.org/api/accounts/163/credentials/quick"
ACCOUNT_163_INVENTORY_API = "https://cookie.meowow.org/api/admin/163/inventory"
SAUTH_API_KEY = os.environ.get("SAUTH_API_KEY", "")

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 指数退避：1s, 2s, 4s

SAUTH_TIMEOUT_SECONDS = 65.0
SAUTH_MAX_ACTIVE = 10
SAUTH_ADMISSION_TIMEOUT_SECONDS = 1.0

# 并发限制：最多同时 5 个请求，防止把上游打挂
_semaphore = asyncio.Semaphore(5)

_sauth_semaphore = asyncio.Semaphore(SAUTH_MAX_ACTIVE)
_sauth_inflight_users: set[str] = set()

# 共享连接池（惰性初始化），复用 TCP 连接提升性能
_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """获取/创建共享 httpx 客户端"""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            verify=False,
            timeout=30,
            limits=httpx.Limits(
                max_connections=10,  # 最大连接数
                max_keepalive_connections=5,  # 保活连接数
            ),
        )
    return _shared_client


def _safe_token(value, pattern):
    text = str(value or "")
    return text if re.fullmatch(pattern, text) else ""


def _safe_response_metadata(resp):
    body = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            body = parsed
    except (TypeError, ValueError):
        pass

    code = _safe_token(body.get("code"), r"[a-z0-9_]{1,64}")
    request_id = _safe_token(
        body.get("requestId") or resp.headers.get("X-Request-Id"),
        r"[A-Za-z0-9._:-]{1,128}",
    )
    attempts = body.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        attempts = None
    retry_after = _safe_token(resp.headers.get("Retry-After"), r"[0-9]{1,5}")
    return body, code, request_id, attempts, retry_after


def _request_suffix(request_id):
    return f"（请求 ID：{request_id}）" if request_id else ""


def _failure_message(status, code, request_id, retry_after):
    suffix = _request_suffix(request_id)
    if status == 404 and code == "inventory_empty":
        return f"4399 库存已空，请稍后再来喵~{suffix}"
    if status == 404:
        return f"4399 服务接口路由不可用，请联系管理员喵~{suffix}"
    if status == 429 and code == "upstream_rate_limited":
        wait = f"，请 {retry_after} 秒后再试" if retry_after else "，请稍后再试"
        return f"4399 服务当前触发限流{wait}喵~{suffix}"
    if status == 503:
        return f"4399 服务当前繁忙，请稍后再试喵~{suffix}"
    if status in (429, 500, 502):
        return f"4399 SAuth 服务暂时不稳定，请稍后再试喵~{suffix}"
    return f"4399 SAuth 获取失败喵：HTTP {status}{suffix}"


def _log_completion(
    status,
    started,
    code="",
    request_id="",
    attempts=None,
    rejected="none",
    level=logging.INFO,
):
    elapsed_ms = int((time.monotonic() - started) * 1000)
    _log.log(
        level,
        "[sauth] status=%s code=%s request_id=%s attempts=%s elapsed_ms=%s rejected=%s",
        status,
        code or "none",
        request_id or "none",
        attempts if attempts is not None else "none",
        elapsed_ms,
        rejected,
    )


async def get_sauth(user_key: str = "") -> tuple[bool, str]:
    """
    获取4399 sauth token
    返回 (是否成功, 消息内容)
    单次调用只向 ACCC 发起一次请求，不在 Bot 层重试
    """
    normalized_user = str(user_key or "").strip()
    started = time.monotonic()
    if normalized_user in _sauth_inflight_users:
        _log_completion(
            "rejected",
            started,
            code="single_flight",
            rejected="single_flight",
        )
        return False, "您已有一个 4399 请求正在处理，请勿重复发送喵~"

    _sauth_inflight_users.add(normalized_user)
    acquired = False
    try:
        try:
            await asyncio.wait_for(
                _sauth_semaphore.acquire(),
                timeout=SAUTH_ADMISSION_TIMEOUT_SECONDS,
            )
            acquired = True
        except asyncio.TimeoutError:
            _log_completion(
                "rejected",
                started,
                code="admission_busy",
                rejected="admission_busy",
            )
            return False, "4399 服务当前繁忙，请稍后再试喵~"

        client = _get_client()
        try:
            resp = await client.post(
                SAUTH_API,
                headers={"X-Api-Key": SAUTH_API_KEY},
                timeout=SAUTH_TIMEOUT_SECONDS,
            )
        except httpx.ConnectError:
            _log_completion(
                "connect_error",
                started,
                code="transport_connect_error",
                level=logging.WARNING,
            )
            return False, "4399 SAuth 获取失败喵：连接服务器失败"
        except httpx.TimeoutException:
            _log_completion(
                "timeout",
                started,
                code="transport_timeout",
                level=logging.WARNING,
            )
            return False, "4399 SAuth 获取失败喵：请求超时"

        data, code, request_id, attempts, retry_after = _safe_response_metadata(resp)
        _log_completion(
            resp.status_code,
            started,
            code=code,
            request_id=request_id,
            attempts=attempts,
        )

        if resp.status_code != 200:
            return False, _failure_message(
                resp.status_code, code, request_id, retry_after
            )

        account_value = data.get("account", "")
        password_value = data.get("password", "")
        sauth_value = data.get("Sauth", "")

        if not account_value or not password_value or not sauth_value:
            return False, "4399 SAuth 获取失败喵：返回数据为空"

        result = (
            "Ciallo～(∠・ω< )⌒★主人您要的东西来啦~\n"
            f"账号：{account_value}\n"
            f"密码：{password_value}\n"
            f"sauth：{sauth_value}"
        )
        return True, result

    except asyncio.CancelledError:
        _log_completion("cancelled", started, code="cancelled")
        raise
    except Exception:
        _log_completion(
            "unexpected",
            started,
            code="unexpected_exception",
            level=logging.ERROR,
        )
        return False, "4399 SAuth 获取失败了喵，请稍后再试~"
    finally:
        if acquired:
            _sauth_semaphore.release()
        _sauth_inflight_users.discard(normalized_user)


# ─── 4399 库存查询 ───────────────────────────────────────────────
SAUTH_STATS_API = "https://cookie.meowow.org/api/admin/stats"
SAUTH_ADMIN_TOKEN = os.environ.get("SAUTH_ADMIN_TOKEN", "")


async def get_4399_stock() -> tuple[bool, int, int, str]:
    """
    查询 4399 账号库存（通过 /api/admin/stats）
    返回 (成功, 可用数量, 总数量, 错误信息)
    """
    try:
        client = _get_client()
        resp = await client.get(
            SAUTH_STATS_API,
            headers={"X-Admin-Token": SAUTH_ADMIN_TOKEN},
        )

        if resp.status_code == 401:
            return False, 0, 0, "4399 库存查询鉴权失败：Admin Token 可能已失效"
        if resp.status_code != 200:
            return False, 0, 0, f"HTTP {resp.status_code}"

        data = resp.json()
        available = int(data.get("available", 0))
        total = int(data.get("total", 0))
        _log.info(f"[4399库存] 查询成功，available={available}, total={total}")
        return True, available, total, ""

    except Exception as e:
        _log.error(f"[4399库存] 查询失败: {e}")
        return False, 0, 0, "4399 库存查询失败了喵，请稍后再试~"


async def get_163_credentials() -> tuple[bool, str]:
    """
    获取 163 小号凭据。
    返回 (是否成功, 消息内容)，失败时不回退本地库存文件。
    """
    async with _semaphore:
        last_status = 0
        try:
            client = _get_client()
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.post(
                        ACCOUNT_163_API,
                        headers={"X-Api-Key": SAUTH_API_KEY},
                    )
                except httpx.ConnectError as e:
                    _log.warning(f"[163] 第 {attempt + 1} 次连接失败: {e}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    return False, "163 获取失败喵：连接服务器失败"
                except httpx.TimeoutException:
                    _log.warning(f"[163] 第 {attempt + 1} 次请求超时")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    return False, "163 获取失败喵：请求超时"

                last_status = resp.status_code

                if resp.status_code == 200:
                    data = resp.json()
                    account_value = str(data.get("account", "") or "").strip()
                    password_value = str(data.get("password", "") or "").strip()

                    if not account_value or not password_value:
                        return False, "163 获取失败喵：返回数据为空"

                    result = (
                        "主人您的163小号来了喵~\n"
                        "━━━━━━━━━━━━━━\n"
                        f"账号：{account_value}\n"
                        f"密码：{password_value}\n"
                        "━━━━━━━━━━━━━━\n"
                        "可能需要手机验证，需要主人自己过验证哦~\n"
                        "爱来自Miracle小号网站"
                    )
                    return True, result

                if resp.status_code >= 500:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    _log.warning(
                        f"[163] 第 {attempt + 1} 次请求失败 HTTP {resp.status_code}，{delay}s 后重试"
                    )
                    await asyncio.sleep(delay)
                    continue

                return False, f"163 获取失败喵：HTTP {resp.status_code}"

            return (
                False,
                f"163 获取失败喵：HTTP {last_status}（已重试 {MAX_RETRIES} 次）",
            )

        except Exception as e:
            _log.error(f"163 获取失败: {e}")
            return False, "163 获取失败了喵，请稍后再试~"


async def get_163_stock() -> tuple[bool, int, int, int, str]:
    """
    查询 163 小号库存。
    返回 (成功, 可用数量, 总数, 已用数量, 错误信息)。
    """
    try:
        client = _get_client()
        resp = await client.get(
            ACCOUNT_163_INVENTORY_API,
            headers={"X-Admin-Token": SAUTH_ADMIN_TOKEN},
        )

        if resp.status_code == 401:
            return False, 0, 0, 0, "163 库存查询鉴权失败：Admin Token 可能已失效"
        if resp.status_code != 200:
            return False, 0, 0, 0, f"HTTP {resp.status_code}"

        data = resp.json()
        available = int(data.get("available", 0))
        total = int(data.get("total", 0))
        used = int(data.get("used", 0))
        _log.info(
            f"[163库存] 查询成功，available={available}, total={total}, used={used}"
        )
        return True, available, total, used, ""

    except Exception as e:
        _log.error(f"[163库存] 查询失败: {e}")
        return False, 0, 0, 0, "163 库存查询失败了喵，请稍后再试~"
