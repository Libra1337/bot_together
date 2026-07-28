"""
4399 Sauth 获取模块
支持多人并发获取（共享连接池 + 信号量限流）
"""

import json
import asyncio
import logging

import httpx

_log = logging.getLogger("QQBot")

SAUTH_API = "https://cookie.meowow.org/api/accounts/sauth/quick"
ACCOUNT_163_API = "https://cookie.meowow.org/api/accounts/163/credentials/quick"
ACCOUNT_163_INVENTORY_API = "https://cookie.meowow.org/api/admin/163/inventory"
SAUTH_API_KEY = "f1856856cc9f4640be12ef0153235df1"

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 指数退避：1s, 2s, 4s

# 并发限制：最多同时 5 个请求，防止把上游打挂
_semaphore = asyncio.Semaphore(5)

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


async def get_sauth() -> tuple[bool, str]:
    """
    获取4399 sauth token
    返回 (是否成功, 消息内容)
    支持多人同时调用，通过信号量限流，共享连接池
    """
    async with _semaphore:
        last_status = 0
        try:
            client = _get_client()
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.post(
                        SAUTH_API,
                        headers={"X-Api-Key": SAUTH_API_KEY},
                    )
                except httpx.ConnectError as e:
                    _log.warning(f"[sauth] 第 {attempt + 1} 次连接失败: {e}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    return False, "4399 sauth 获取失败喵：连接服务器失败"
                except httpx.TimeoutException:
                    _log.warning(f"[sauth] 第 {attempt + 1} 次请求超时")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    return False, "4399 sauth 获取失败喵：请求超时"

                last_status = resp.status_code

                if resp.status_code == 200:
                    data = resp.json()
                    account_value = data.get("account", "")
                    password_value = data.get("password", "")
                    sauth_value = data.get("Sauth", "")

                    if not account_value or not password_value or not sauth_value:
                        return False, "4399 sauth 获取失败喵：返回数据为空"

                    result = (
                        "Ciallo～(∠・ω< )⌒★主人您要的东西来啦~\n"
                        f"账号：{account_value}\n"
                        f"密码：{password_value}\n"
                        f"sauth：{sauth_value}"
                    )
                    return True, result

                # 5xx 服务端错误 → 重试
                if resp.status_code >= 500:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    _log.warning(
                        f"[sauth] 第 {attempt + 1} 次请求失败 HTTP {resp.status_code}，{delay}s 后重试"
                    )
                    await asyncio.sleep(delay)
                    continue

                # 其他错误码（4xx 等）不重试
                return False, f"4399 sauth 获取失败喵：HTTP {resp.status_code}"

            # 所有重试都失败了
            return (
                False,
                f"4399 sauth 获取失败喵：HTTP {last_status}（已重试 {MAX_RETRIES} 次）",
            )

        except Exception as e:
            _log.error(f"4399 sauth 获取失败: {e}")
            return False, "4399 sauth 获取失败了喵，请稍后再试~"


# ─── 4399 库存查询 ───────────────────────────────────────────────
SAUTH_STATS_API = "https://cookie.meowow.org/api/admin/stats"
SAUTH_ADMIN_TOKEN = "6a508f5782f0430c41a20b2d06a8b645472b4a67c53fe5aea0b47a3ab580937e"


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
