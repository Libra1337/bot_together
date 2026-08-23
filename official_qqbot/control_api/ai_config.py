from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import yaml


@dataclass(frozen=True)
class AISettings:
    base_url: str
    model: str
    api_key: str


CommandRunner = Callable[..., subprocess.CompletedProcess]


class AIConfigManager:
    def __init__(
        self,
        config_path: str | Path,
        *,
        client_factory: Callable[..., Any] | None = None,
        command_runner: CommandRunner | None = None,
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
        self.config_path = Path(config_path)
        self.client_factory = client_factory or httpx.AsyncClient
        self.command_runner = command_runner or subprocess.run
        self.restart_command = restart_command
        self.status_command = status_command

    def load(self) -> AISettings:
        payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
        ai = payload.get("ai") or {}
        if not isinstance(ai, dict):
            ai = {}
        return AISettings(
            base_url=str(ai.get("base_url") or "").strip(),
            model=str(ai.get("model") or "").strip(),
            api_key=str(ai.get("api_key") or "").strip(),
        )

    def public_settings(self) -> dict[str, str | bool]:
        settings = self.load()
        return {
            "base_url": settings.base_url,
            "model": settings.model,
            "api_key_configured": bool(settings.api_key),
            "api_key_masked": _mask_api_key(settings.api_key),
        }

    @staticmethod
    def validate(settings: AISettings) -> str | None:
        parsed = urlparse(settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "API 地址必须是有效的 http 或 https 地址"
        if not settings.model.strip():
            return "模型名称不能为空"
        if not settings.api_key.strip():
            return "API Key 不能为空"
        return None

    async def check(self, settings: AISettings) -> tuple[bool, str]:
        validation_error = self.validate(settings)
        if validation_error:
            return False, validation_error

        endpoint = f"{settings.base_url.rstrip('/')}/chat/completions"
        try:
            async with self.client_factory(timeout=15.0) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "temperature": 0,
                    },
                )
        except httpx.TimeoutException:
            return False, "连接超时"
        except httpx.RequestError:
            return False, "无法连接到 API 地址"
        except Exception:
            return False, "检测请求失败"

        if response.status_code < 200 or response.status_code >= 300:
            return False, f"API 返回 HTTP {response.status_code}"
        try:
            payload = response.json()
        except (TypeError, ValueError):
            return False, "API 返回格式无效"
        if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
            return False, "API 返回中没有有效回复"
        if not payload["choices"]:
            return False, "API 返回中没有有效回复"
        return True, "连接成功"

    def save(self, settings: AISettings) -> bytes:
        validation_error = self.validate(settings)
        if validation_error:
            raise ValueError(validation_error)
        original = self.config_path.read_bytes()
        payload = yaml.safe_load(original.decode("utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("配置文件格式无效")
        ai = payload.setdefault("ai", {})
        if not isinstance(ai, dict):
            raise ValueError("AI 配置格式无效")
        ai["base_url"] = settings.base_url
        ai["api_key"] = settings.api_key
        ai["model"] = settings.model
        self._atomic_write(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=False,
            ).encode("utf-8")
        )
        return original

    def restore(self, snapshot: bytes) -> None:
        self._atomic_write(snapshot)

    def restart_bot(self) -> tuple[bool, str]:
        try:
            restart = self.command_runner(
                list(self.restart_command),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if restart.returncode != 0:
                return False, "Bot 重启失败"
            status = self.command_runner(
                list(self.status_command),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "Bot 重启失败"
        if status.returncode != 0 or status.stdout.strip() != "active":
            return False, "Bot 未处于运行状态"
        return True, "Bot 已重启并使用新配置"

    def _atomic_write(self, content: bytes) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.",
            suffix=".tmp",
            dir=self.config_path.parent,
        )
        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, self.config_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def _mask_api_key(api_key: str) -> str:
    value = str(api_key or "")
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"
