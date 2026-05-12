"""
AI 对话模块（QQ 官方 Bot 版本）
"""

import logging
import httpx
from collections import OrderedDict

_log = logging.getLogger("OfficialBot")

# 对话上下文 {chat_id: [{"role": ..., "content": ...}]}
_chat_history: OrderedDict = OrderedDict()
MAX_HISTORY_CHATS = 200


class AIChat:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        max_history: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_history = max_history
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def chat(self, chat_id: str, user_message: str) -> str:
        """发送消息并获取 AI 回复"""
        # 获取/创建对话历史
        if chat_id not in _chat_history:
            _chat_history[chat_id] = []
            while len(_chat_history) > MAX_HISTORY_CHATS:
                _chat_history.popitem(last=False)

        history = _chat_history[chat_id]
        history.append({"role": "user", "content": user_message})

        # 截断历史
        if len(history) > self.max_history * 2:
            history[:] = history[-(self.max_history * 2) :]

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(history)

        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.7,
                    "top_p": 0.9,
                },
            )

            if resp.status_code != 200:
                _log.warning(f"[AI] API 返回 {resp.status_code}: {resp.text[:200]}")
                return "AI 暂时无法回复，请稍后再试喵~"

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return "AI 返回为空喵~"

            reply = choices[0].get("message", {}).get("content", "").strip()
            if not reply:
                return "AI 返回为空喵~"

            # 记录 AI 回复到历史
            history.append({"role": "assistant", "content": reply})
            return reply

        except Exception as e:
            _log.error(f"[AI] 请求失败: {e}")
            return "AI 暂时无法回复，请稍后再试喵~"

    def clear_history(self, chat_id: str):
        """清除指定对话的历史"""
        _chat_history.pop(chat_id, None)
