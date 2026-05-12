"""
AI 对话处理器
基于 OpenAI 兼容接口，支持上下文记忆
多 API Key 轮询 + 重试 + Key 健康跟踪 + httpx 异步连接池
"""

import json
import asyncio
import logging
import time

import httpx

from datetime import datetime
from collections import defaultdict

_log = logging.getLogger("QQBot")

# Key 冷却时间（秒）：某个 Key 出错后暂时不用
KEY_COOLDOWN = 60
# 每个请求最大重试次数（每次换 Key）
MAX_RETRIES = 3
# httpx 超时配置（秒）
HTTP_CONNECT_TIMEOUT = 10
HTTP_READ_TIMEOUT = 120  # 读取超时（AI 生成可能很慢）
HTTP_WRITE_TIMEOUT = 10
HTTP_POOL_TIMEOUT = 30  # 等待连接池空闲连接的超时

# 默认 / 最大 token 限制
DEFAULT_MAX_TOKENS = 2048
LONG_FORM_MAX_TOKENS = 4096

# 用户上限：超过此数量时清理最不活跃的一半
MAX_USERS = 200

# 并发控制：当前 API 单 key 最多支持 10 并发
MAX_CONCURRENT_AI = 10


class AIChat:
    """AI 对话处理器，多 Key 轮询 + 自动重试 + Key 健康跟踪 + httpx 异步连接池"""

    def __init__(
        self,
        base_url: str,
        api_keys: list,
        model: str,
        system_prompt: str = "",
        max_history: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.system_prompt = system_prompt
        self.max_history = max_history

        # 解析 Key 配置：支持 {key, model} 格式和纯字符串格式
        self.key_configs = []
        for item in api_keys:
            if isinstance(item, dict):
                self.key_configs.append(
                    {
                        "key": item["key"],
                        "model": item.get("model", model),
                    }
                )
            else:
                self.key_configs.append(
                    {
                        "key": item,
                        "model": model,
                    }
                )

        # 轮询索引
        self._index = 0
        self._key_lock = asyncio.Lock()

        # Key 健康状态：记录每个 Key 上次出错的时间
        # {key_str: timestamp}  如果当前时间 - timestamp < KEY_COOLDOWN 则跳过
        self._key_errors: dict[str, float] = {}

        # 每个用户的对话历史 {user_id: [messages]}
        self.histories: dict[str, list] = defaultdict(list)

        # 每个用户最后活跃时间 {user_id: timestamp}
        self._last_active: dict[str, float] = {}

        # ====== 并发控制 ======
        # 信号量：限制同时进行的 AI 请求数量
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_AI)
        # 并发统计
        self._active_requests = 0  # 当前正在进行的请求数
        self._total_requests = 0  # 总请求数
        self._total_success = 0  # 成功请求数
        self._total_failed = 0  # 失败请求数
        self._stats_lock = asyncio.Lock()  # 统计数据锁

        # ====== httpx 异步客户端（连接池复用） ======
        self._http_client: httpx.AsyncClient | None = None

        _log.info(
            f"AI 已加载 {len(self.key_configs)} 个 API Key，"
            f"轮询使用（最大重试 {MAX_RETRIES} 次，"
            f"最大并发 {MAX_CONCURRENT_AI}）"
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 异步客户端（懒初始化，连接池复用）"""
        if self._http_client is None or self._http_client.is_closed:
            timeout = httpx.Timeout(
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_WRITE_TIMEOUT,
                pool=HTTP_POOL_TIMEOUT,
            )
            # 连接池：与 AI 并发上限匹配，避免连接池成为瓶颈
            limits = httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=300,  # 连接保活 5 分钟
            )
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                http2=False,
                follow_redirects=True,
                verify=False,  # 跳过 SSL 验证（与原 curl --noproxy 行为一致）
            )
            _log.info("[AI] httpx 异步客户端已创建（连接池复用）")
        return self._http_client

    async def close(self):
        """关闭 httpx 客户端，释放连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            _log.info("[AI] httpx 客户端已关闭")

    def _is_key_healthy(self, key: str) -> bool:
        """检查 Key 是否处于冷却期"""
        err_time = self._key_errors.get(key)
        if err_time is None:
            return True
        return (time.time() - err_time) > KEY_COOLDOWN

    def _mark_key_error(self, key: str):
        """标记 Key 为出错状态"""
        self._key_errors[key] = time.time()
        _log.warning(f"[AI] Key ...{key[-6:]} 标记为冷却状态 ({KEY_COOLDOWN}s)")

    def _mark_key_success(self, key: str):
        """清除 Key 的错误标记"""
        self._key_errors.pop(key, None)

    async def _next_key_config(self, exclude_keys: set = None) -> dict | None:
        """获取下一个健康的 Key 配置，跳过冷却中和已排除的 Key"""
        if exclude_keys is None:
            exclude_keys = set()

        async with self._key_lock:
            total = len(self.key_configs)
            for _ in range(total):
                cfg = self.key_configs[self._index % total]
                self._index += 1
                key = cfg["key"]
                if key in exclude_keys:
                    continue
                if self._is_key_healthy(key):
                    return cfg

            # 所有 Key 都在冷却中或被排除，强制返回下一个（冷却最久的）
            oldest_key = None
            oldest_time = float("inf")
            for cfg in self.key_configs:
                key = cfg["key"]
                if key in exclude_keys:
                    continue
                err_time = self._key_errors.get(key, 0)
                if err_time < oldest_time:
                    oldest_time = err_time
                    oldest_key = cfg

            if oldest_key:
                _log.warning(
                    f"[AI] 所有 Key 冷却中，强制使用 Key ...{oldest_key['key'][-6:]}"
                )
                return oldest_key

            # 连排除的都没有了，返回任意一个
            cfg = self.key_configs[self._index % total]
            self._index += 1
            return cfg

    async def _update_stats(self, success: bool):
        """更新并发统计"""
        async with self._stats_lock:
            if success:
                self._total_success += 1
            else:
                self._total_failed += 1

    def get_stats(self) -> dict:
        """获取当前并发统计信息"""
        return {
            "active": self._active_requests,
            "total": self._total_requests,
            "success": self._total_success,
            "failed": self._total_failed,
            "max_concurrent": MAX_CONCURRENT_AI,
        }

    @staticmethod
    def _detect_max_tokens(content: str) -> int:
        """根据用户消息内容动态决定 max_tokens

        如果用户请求长文、论文、故事等，自动提高 token 上限
        """
        import re

        # 检测用户指定字数的请求，如："写一篇1000字的文章"
        num_match = re.search(r"(\d+)\s*(?:字|词|word)", content)
        if num_match:
            desired_chars = int(num_match.group(1))
            # 中文大约 1.5 token/字，留一些余量
            estimated_tokens = int(desired_chars * 2)
            return min(max(estimated_tokens, DEFAULT_MAX_TOKENS), LONG_FORM_MAX_TOKENS)

        # 检测长文关键词
        long_keywords = [
            "长文",
            "论文",
            "文章",
            "作文",
            "小说",
            "故事",
            "完整",
            "详细",
            "详述",
            "展开",
            "深入",
            "全面",
            "写一篇",
            "写篇",
            "长一点",
            "多写一些",
            "多写点",
            "别太短",
            "不要太短",
            "写长一点",
            "尽可能长",
            "越长越好",
            "仔细写",
        ]
        if any(kw in content for kw in long_keywords):
            return LONG_FORM_MAX_TOKENS

        return DEFAULT_MAX_TOKENS

    async def chat(self, user_id: str, content: str, group_context: list = None) -> str:
        """发送消息给 AI 并获取回复（带并发控制）"""
        # 更新活跃时间
        self._last_active[user_id] = time.time()

        # 用户数量超限时淘汰不活跃用户
        if len(self.histories) > MAX_USERS:
            self._evict_inactive()

        # 添加用户消息到历史
        self.histories[user_id].append({"role": "user", "content": content})

        # 限制历史长度
        if len(self.histories[user_id]) > self.max_history * 2:
            self.histories[user_id] = self.histories[user_id][-(self.max_history * 2) :]

        # 动态决定 max_tokens
        max_tokens = self._detect_max_tokens(content)
        if max_tokens > DEFAULT_MAX_TOKENS:
            _log.info(f"[AI] 检测到长文请求，max_tokens={max_tokens}")

        # 构建消息列表
        messages = []
        if self.system_prompt:
            now = datetime.now()
            time_info = f"\n\n[实时信息] 当前时间：{now.strftime('%Y年%m月%d日 %H:%M:%S')} 星期{'一二三四五六日'[now.weekday()]}"

            news_info = ""
            if self._needs_news(content):
                news_info = await self._fetch_news()

            # 群聊上下文：让 AI 看到近期群聊记录
            ctx_info = ""
            if group_context:
                ctx_lines = [
                    f"{m['nickname']}: {m['content']}" for m in group_context[-15:]
                ]
                ctx_info = (
                    "\n\n[群聊近期对话记录（供你参考上下文，自然地参与话题）]\n"
                    + "\n".join(ctx_lines)
                )

            messages.append(
                {
                    "role": "system",
                    "content": self.system_prompt + time_info + news_info + ctx_info,
                }
            )
        messages.extend(self.histories[user_id])

        # ====== 并发控制：通过 Semaphore 限制同时请求数 ======
        self._total_requests += 1
        self._active_requests += 1
        _log.info(
            f"[AI] 并发状态：{self._active_requests}/{MAX_CONCURRENT_AI} "
            f"(总计:{self._total_requests} 成功:{self._total_success} 失败:{self._total_failed})"
        )

        try:
            async with self._semaphore:
                reply = await self._request_with_retry(messages, max_tokens=max_tokens)

            # 添加 AI 回复到历史
            self.histories[user_id].append({"role": "assistant", "content": reply})
            await self._update_stats(success=True)
            return reply

        except Exception as e:
            _log.error(f"AI 请求失败（所有重试均失败）: {e}")
            self.histories[user_id].pop()
            await self._update_stats(success=False)
            return "AI 暂时无法回复，请稍后再试~"
        finally:
            self._active_requests -= 1

    async def _request_with_retry(
        self, messages: list, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> str:
        """带重试的请求：每次失败自动换 Key 重试"""
        last_error = None
        tried_keys: set[str] = set()

        for attempt in range(1, MAX_RETRIES + 1):
            cfg = await self._next_key_config(exclude_keys=tried_keys)
            if cfg is None:
                break

            api_key = cfg["key"]
            tried_keys.add(api_key)

            try:
                result = await self._request(messages, cfg, max_tokens=max_tokens)
                self._mark_key_success(api_key)
                return result
            except Exception as e:
                last_error = e
                self._mark_key_error(api_key)
                _log.warning(
                    f"[AI] 第 {attempt}/{MAX_RETRIES} 次请求失败 (Key ...{api_key[-6:]}): {e}"
                )
                if attempt < MAX_RETRIES:
                    # 短暂等待后重试
                    await asyncio.sleep(0.5)

        raise last_error or Exception("所有 API Key 请求均失败")

    async def _request(
        self, messages: list, cfg: dict, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> str:
        """使用 httpx 异步客户端调用 OpenAI 兼容接口（连接池复用）"""
        api_key = cfg["key"]
        model = cfg["model"]
        _log.info(
            f"[AI] 使用 Key: ...{api_key[-6:]} 模型: {model} max_tokens={max_tokens}"
        )

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        client = self._get_http_client()
        start_time = time.time()

        try:
            response = await client.post(url, json=payload, headers=headers)
            elapsed = time.time() - start_time
            _log.info(f"[AI] 请求耗时: {elapsed:.2f}s 状态码: {response.status_code}")
        except httpx.ConnectTimeout:
            raise Exception(f"连接超时 ({HTTP_CONNECT_TIMEOUT}s)")
        except httpx.ReadTimeout:
            raise Exception(f"读取超时 ({HTTP_READ_TIMEOUT}s)")
        except httpx.PoolTimeout:
            raise Exception(f"连接池繁忙，等待超时 ({HTTP_POOL_TIMEOUT}s)")
        except httpx.ConnectError as e:
            raise Exception(f"连接失败: {e}")
        except Exception as e:
            raise Exception(f"httpx 请求异常: {e}")

        raw = response.text.strip()

        if response.status_code >= 500:
            raise Exception(f"API 返回 HTTP {response.status_code}: {raw[:150]}")

        if not raw:
            raise Exception(f"AI 返回空响应 (HTTP {response.status_code})")

        # 检查是否是 HTML 错误页面（502/503 等）
        if raw.startswith("<") or "502 Bad Gateway" in raw or "503 Service" in raw:
            raise Exception(f"API 返回 HTTP 错误页面: {raw[:150]}")

        _log.info(f"[AI原始响应] {raw[:200]}")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise Exception(f"API 返回非 JSON: {raw[:200]}")

        if "error" in data:
            error_info = data["error"]
            error_msg = (
                error_info.get("message", str(error_info))
                if isinstance(error_info, dict)
                else str(error_info)
            )
            raise Exception(f"API 错误: {error_msg}")

        choices = data.get("choices", [])
        if not choices:
            raise Exception("AI 返回空 choices")

        return choices[0]["message"]["content"].strip()

    def clear_history(self, user_id: str):
        """清除指定用户的对话历史"""
        self.histories.pop(user_id, None)
        self._last_active.pop(user_id, None)
        _log.info(f"已清除用户 {user_id} 的对话历史")

    def cleanup_inactive(self, max_age: float = 7200) -> int:
        """清理超过 max_age 秒不活跃的用户对话历史，返回清理数量"""
        now = time.time()
        inactive_users = [
            uid for uid, ts in self._last_active.items() if now - ts > max_age
        ]
        for uid in inactive_users:
            self.histories.pop(uid, None)
            self._last_active.pop(uid, None)
        if inactive_users:
            _log.info(f"[AI] 清理了 {len(inactive_users)} 个不活跃用户的对话历史")
        return len(inactive_users)

    def _evict_inactive(self):
        """当用户数量超限时，淘汰最不活跃的一半"""
        if len(self.histories) <= MAX_USERS:
            return
        # 按活跃时间排序，淘汰最旧的一半
        sorted_users = sorted(self._last_active.items(), key=lambda x: x[1])
        evict_count = len(sorted_users) // 2
        for uid, _ in sorted_users[:evict_count]:
            self.histories.pop(uid, None)
            self._last_active.pop(uid, None)
        _log.info(
            f"[AI] 用户数超限({MAX_USERS})，淘汰了 {evict_count} 个最不活跃的用户"
        )

    @staticmethod
    def _needs_news(content: str) -> bool:
        """判断用户消息是否在问新闻"""
        keywords = ["新闻", "热点", "热搜", "最新消息", "今天发生", "最近发生", "头条"]
        return any(kw in content for kw in keywords)

    async def _fetch_news(self) -> str:
        """使用 httpx 获取最新新闻"""
        client = self._get_http_client()

        try:
            response = await client.get(
                "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=10",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            raw = response.text.strip()

            if raw:
                data = json.loads(raw)
                items = data.get("data", [])
                if items:
                    news_list = []
                    for i, item in enumerate(items[:10], 1):
                        target = item.get("target", {})
                        title = target.get("title", "")
                        excerpt = target.get("excerpt", "")
                        if title:
                            news_list.append(f"{i}. {title}")
                            if excerpt:
                                news_list.append(f"   {excerpt[:60]}")

                    if news_list:
                        return "\n\n[今日热点新闻]\n" + "\n".join(news_list)
        except Exception as e:
            _log.warning(f"获取新闻失败: {e}")

        # 备用：用百度热搜
        try:
            response = await client.get(
                "https://top.baidu.com/board?tab=realtime",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            raw = response.text

            import re

            titles = re.findall(r'"word":"([^"]+)"', raw)
            if titles:
                news_list = [f"{i}. {t}" for i, t in enumerate(titles[:10], 1)]
                return "\n\n[今日热搜新闻]\n" + "\n".join(news_list)
        except Exception as e:
            _log.warning(f"获取百度热搜失败: {e}")

        return "\n\n[新闻获取失败，请告诉主人暂时无法获取新闻]"
