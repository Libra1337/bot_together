"""
Language-flexible plugin runtime for the QQ bot.

Plugins live under plugins/<plugin-id>/plugin.json. Python plugins are imported
in-process. External plugins are launched as commands and exchange one JSON
event on stdin for one JSON response on stdout.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_log = logging.getLogger("OfficialBot")


@dataclass
class Plugin:
    id: str
    name: str
    type: str
    entry: str
    commands: list[str]
    enabled: bool
    directory: Path
    manifest: dict[str, Any]
    module: Any = None


class PluginAPI:
    def __init__(self, reply_func):
        self._reply_func = reply_func

    async def reply(self, ctx: dict[str, Any], text: str):
        await self._reply_func(ctx, text)


class PluginRuntime:
    def __init__(
        self,
        plugins_dir: str | os.PathLike[str] = "plugins",
        state_file: str | os.PathLike[str] = "data/plugins.json",
        reply_func=None,
    ):
        self.plugins_dir = Path(plugins_dir)
        self.state_file = Path(state_file)
        self.reply_func = reply_func
        self.plugins: list[Plugin] = []
        self._fingerprint = ""
        self.reload()

    def _load_state(self) -> dict[str, Any]:
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("[Plugin] Failed to read state file: %s", exc)
        return {}

    def _load_manifest(self, plugin_dir: Path) -> dict[str, Any] | None:
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("[Plugin] Failed to parse %s: %s", manifest_path, exc)
            return None

    def _load_python_module(self, plugin: Plugin):
        entry_path = plugin.directory / plugin.entry
        if not entry_path.exists():
            _log.warning("[Plugin:%s] Entry not found: %s", plugin.id, entry_path)
            return None

        module_name = f"qqbot_plugin_{plugin.id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            _log.warning("[Plugin:%s] Cannot load module spec", plugin.id)
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def reload(self):
        state = self._load_state()
        state_plugins = state.get("plugins", {}) if isinstance(state, dict) else {}
        loaded: list[Plugin] = []

        if not self.plugins_dir.exists():
            self.plugins = []
            self._fingerprint = self._build_fingerprint()
            return

        for plugin_dir in sorted(p for p in self.plugins_dir.iterdir() if p.is_dir()):
            manifest = self._load_manifest(plugin_dir)
            if not manifest:
                continue

            plugin_id = str(manifest.get("id") or plugin_dir.name)
            saved = state_plugins.get(plugin_id, {})
            enabled = (
                bool(saved["enabled"])
                if isinstance(saved, dict) and isinstance(saved.get("enabled"), bool)
                else manifest.get("enabled", True) is not False
            )
            plugin = Plugin(
                id=plugin_id,
                name=str(manifest.get("name") or plugin_id),
                type=str(manifest.get("type") or "python"),
                entry=str(manifest.get("entry") or ""),
                commands=[str(cmd).lower() for cmd in manifest.get("commands", [])],
                enabled=enabled,
                directory=plugin_dir,
                manifest=manifest,
            )
            if plugin.enabled and plugin.type == "python":
                try:
                    plugin.module = self._load_python_module(plugin)
                except Exception as exc:
                    _log.warning("[Plugin:%s] Load failed: %s", plugin.id, exc)
                    plugin.enabled = False
            loaded.append(plugin)

        self.plugins = loaded
        self._fingerprint = self._build_fingerprint()
        _log.info("[Plugin] Loaded %s plugin(s)", len(self.plugins))

    def _build_fingerprint(self) -> str:
        parts: list[str] = []
        paths = [self.state_file]
        if self.plugins_dir.exists():
            for plugin_dir in sorted(p for p in self.plugins_dir.iterdir() if p.is_dir()):
                paths.append(plugin_dir / "plugin.json")
                manifest = self._load_manifest(plugin_dir)
                if manifest and manifest.get("type", "python") == "python":
                    paths.append(plugin_dir / str(manifest.get("entry") or "plugin.py"))
        for path in paths:
            try:
                stat = path.stat()
                parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
            except FileNotFoundError:
                parts.append(f"{path}:missing")
        return "|".join(parts)

    def reload_if_changed(self):
        current = self._build_fingerprint()
        if current != self._fingerprint:
            self.reload()

    def _matches(self, plugin: Plugin, content: str) -> bool:
        if not plugin.enabled:
            return False
        if not plugin.commands:
            return True
        lower = content.lower().strip()
        return any(lower == cmd or lower.startswith(f"{cmd} ") for cmd in plugin.commands)

    async def _run_external(self, plugin: Plugin, event: dict[str, Any]) -> dict[str, Any] | None:
        command = plugin.manifest.get("command")
        args = plugin.manifest.get("args", [])
        if not command:
            return None
        proc = await asyncio.create_subprocess_exec(
            str(command),
            *[str(arg) for arg in args],
            cwd=str(plugin.directory),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=15)
        if stderr:
            _log.warning("[Plugin:%s] stderr: %s", plugin.id, stderr.decode("utf-8", "ignore")[:300])
        if proc.returncode != 0 or not stdout:
            return None
        return json.loads(stdout.decode("utf-8"))

    async def dispatch(self, event: dict[str, Any]) -> dict[str, Any] | None:
        self.reload_if_changed()
        content = str(event.get("content") or "")
        api = PluginAPI(self.reply_func) if self.reply_func else None

        for plugin in self.plugins:
            if not self._matches(plugin, content):
                continue
            try:
                result = None
                if plugin.type == "python" and plugin.module and hasattr(plugin.module, "handle"):
                    result = plugin.module.handle(event, api)
                    if asyncio.iscoroutine(result):
                        result = await result
                elif plugin.type in {"external", "command"}:
                    result = await self._run_external(plugin, event)

                if result and result.get("handled"):
                    return result
            except Exception as exc:
                _log.warning("[Plugin:%s] Dispatch failed: %s", plugin.id, exc)
                return {"handled": True, "reply": f"插件 {plugin.name} 执行失败喵~"}

        return None
