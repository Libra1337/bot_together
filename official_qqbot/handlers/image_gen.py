"""OpenAI-compatible AI image generation helpers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


_log = logging.getLogger("OfficialBot")

_EXPLICIT_COMMAND_RE = re.compile(r"^\s*/?(?:生图|绘图)\s*(.*?)\s*$", re.IGNORECASE)
_NATURAL_IMAGE_PATTERNS = (
    re.compile(
        r"^\s*(?:帮我|给我|请)?(?:生成|画|绘制)(?:一张|一幅|一个|几张)?\s*.+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:我)?想要(?:一张|一幅|一个)?\s*.+(?:图片|的图|壁纸|头像|照片|插画)\s*$",
        re.IGNORECASE,
    ),
)
_NATURAL_PREFIX_RE = re.compile(
    r"^\s*(?:(?:帮我|给我|请)?(?:生成|画|绘制)|(?:我)?想要)"
    r"(?:一张|一幅|一个|几张)?\s*",
    re.IGNORECASE,
)
_TRAILING_IMAGE_WORD_RE = re.compile(
    r"\s*(?:的图片|的图|图片|图|的壁纸|壁纸|的头像|头像|的照片|照片|的插画|插画)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GeneratedImage:
    url: str = ""
    b64_json: str = ""


def is_image_request(content: str) -> bool:
    value = str(content or "").strip()
    if _EXPLICIT_COMMAND_RE.fullmatch(value):
        return True
    return any(pattern.search(value) for pattern in _NATURAL_IMAGE_PATTERNS)


def extract_image_prompt(content: str) -> str:
    value = str(content or "").strip()
    explicit = _EXPLICIT_COMMAND_RE.fullmatch(value)
    if explicit:
        return explicit.group(1).strip()

    cleaned = _NATURAL_PREFIX_RE.sub("", value, count=1)
    cleaned = _TRAILING_IMAGE_WORD_RE.sub("", cleaned, count=1)
    return cleaned.strip()


class ImageGenerator:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        size: str = "1024x1024",
        client_factory: Callable[..., Any] | None = None,
    ):
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.size = str(size or "1024x1024").strip()
        self.client_factory = client_factory or httpx.AsyncClient

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def generate(self, prompt: str) -> tuple[GeneratedImage | None, str]:
        if not self.configured:
            return None, "AI 生图尚未配置，请联系管理员"
        if not str(prompt or "").strip():
            return None, "请在 /生图 后面填写图片描述"

        endpoint = f"{self.base_url.rstrip('/')}/images/generations"
        try:
            async with self.client_factory(timeout=90.0) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "prompt": str(prompt).strip(),
                        "n": 1,
                        "size": self.size,
                    },
                )
        except httpx.TimeoutException:
            return None, "生图服务响应超时，请稍后再试"
        except httpx.RequestError:
            return None, "无法连接生图服务，请稍后再试"
        except Exception as exc:
            _log.warning("[AI生图] 请求异常: %s", type(exc).__name__)
            return None, "生图请求失败，请稍后再试"

        if response.status_code < 200 or response.status_code >= 300:
            return None, f"生图 API 返回 HTTP {response.status_code}"

        try:
            payload = response.json()
        except (TypeError, ValueError):
            return None, "生图接口返回格式无效"

        data = payload.get("data") if isinstance(payload, dict) else None
        first = data[0] if isinstance(data, list) and data else None
        if not isinstance(first, dict):
            return None, "生图接口返回中没有图片"

        image_url = str(first.get("url") or "").strip()
        if image_url:
            parsed_url = urlparse(image_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                return None, "生图接口返回了无效的图片地址"
            return GeneratedImage(url=image_url), ""

        b64_json = str(first.get("b64_json") or "").strip()
        if b64_json:
            return GeneratedImage(b64_json=b64_json), ""

        return None, "生图接口返回中没有图片"
