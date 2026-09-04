"""Configuration management for the dashboard image generation page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml

from control_api.ai_config import AIConfigManager, _mask_api_key
from handlers.image_gen import GeneratedImage, ImageGenerator


IMAGE_SIZES = ("1024x1024", "1024x1536", "1536x1024")


@dataclass(frozen=True)
class ImageAISettings:
    enabled: bool
    base_url: str
    model: str
    api_key: str
    size: str
    cooldown_seconds: int


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


class ImageAIConfigManager(AIConfigManager):
    def __init__(
        self,
        config_path: str | Path,
        *,
        client_factory: Callable[..., Any] | None = None,
        command_runner=None,
        restart_command: tuple[str, ...] = (
            "systemctl",
            "restart",
            "official-qqbot",
        ),
        status_command: tuple[str, ...] = (
            "systemctl",
            "is-active",
            "official-qqbot",
        ),
    ):
        super().__init__(
            config_path,
            client_factory=client_factory,
            command_runner=command_runner,
            restart_command=restart_command,
            status_command=status_command,
        )

    def load(self) -> ImageAISettings:
        payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
        image_ai = payload.get("image_ai") or {}
        if not isinstance(image_ai, dict):
            image_ai = {}
        try:
            cooldown_seconds = int(image_ai.get("cooldown_seconds", 60))
        except (TypeError, ValueError):
            cooldown_seconds = 60
        return ImageAISettings(
            enabled=_as_bool(image_ai.get("enabled", False)),
            base_url=str(image_ai.get("base_url") or "").strip(),
            model=str(image_ai.get("model") or "grok-imagine-1.0-fast").strip(),
            api_key=str(image_ai.get("api_key") or "").strip(),
            size=str(image_ai.get("size") or "1024x1024").strip(),
            cooldown_seconds=cooldown_seconds,
        )

    def public_settings(self) -> dict[str, str | int | bool]:
        settings = self.load()
        return {
            "enabled": settings.enabled,
            "base_url": settings.base_url,
            "model": settings.model,
            "api_key_configured": bool(settings.api_key),
            "api_key_masked": _mask_api_key(settings.api_key),
            "size": settings.size,
            "cooldown_seconds": settings.cooldown_seconds,
        }

    @staticmethod
    def validate(
        settings: ImageAISettings, *, require_credentials: bool | None = None
    ) -> str | None:
        if require_credentials is None:
            require_credentials = settings.enabled
        if require_credentials:
            parsed = urlparse(settings.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return "API 地址必须是有效的 http 或 https 地址"
            if not settings.model.strip():
                return "生图模型不能为空"
            if not settings.api_key.strip():
                return "API Key 不能为空"
        if settings.size not in IMAGE_SIZES:
            return "图片尺寸不受支持"
        if settings.cooldown_seconds < 0 or settings.cooldown_seconds > 86400:
            return "用户冷却时间必须在 0 到 86400 秒之间"
        return None

    async def check(
        self, settings: ImageAISettings
    ) -> tuple[bool, str, GeneratedImage | None]:
        validation_error = self.validate(settings, require_credentials=True)
        if validation_error:
            return False, validation_error, None
        generator = ImageGenerator(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            size=settings.size,
            client_factory=self.client_factory,
        )
        image, error = await generator.generate("一枚简洁的蓝色圆形图标，纯色背景")
        if not image:
            return False, error, None
        return True, "生图连接成功", image

    def save(self, settings: ImageAISettings) -> bytes:
        validation_error = self.validate(settings)
        if validation_error:
            raise ValueError(validation_error)
        original = self.config_path.read_bytes()
        payload = yaml.safe_load(original.decode("utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("配置文件格式无效")
        image_ai = payload.setdefault("image_ai", {})
        if not isinstance(image_ai, dict):
            raise ValueError("AI 生图配置格式无效")
        image_ai.update(
            {
                "enabled": settings.enabled,
                "base_url": settings.base_url,
                "api_key": settings.api_key,
                "model": settings.model,
                "size": settings.size,
                "cooldown_seconds": settings.cooldown_seconds,
            }
        )
        self._atomic_write(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode("utf-8")
        )
        return original
