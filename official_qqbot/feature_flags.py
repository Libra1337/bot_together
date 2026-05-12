from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


_log = logging.getLogger("OfficialBot")


class FeatureFlags:
    def __init__(self, state_file: str | Path = "data/plugins.json"):
        self.state_file = Path(state_file)
        self._mtime_ns: int | None = None
        self._state: dict[str, Any] = {}
        self.reload()

    def reload(self):
        try:
            if self.state_file.exists():
                stat = self.state_file.stat()
                self._mtime_ns = stat.st_mtime_ns
                self._state = json.loads(self.state_file.read_text(encoding="utf-8"))
                return
        except Exception as exc:
            _log.warning("[FeatureFlags] Failed to load %s: %s", self.state_file, exc)
        self._mtime_ns = None
        self._state = {}

    def reload_if_changed(self):
        try:
            current = self.state_file.stat().st_mtime_ns if self.state_file.exists() else None
        except OSError:
            current = None
        if current != self._mtime_ns:
            self.reload()

    def enabled(self, feature_id: str) -> bool:
        self.reload_if_changed()
        plugins = self._state.get("plugins", {})
        item = plugins.get(feature_id, {}) if isinstance(plugins, dict) else {}
        enabled = item.get("enabled") if isinstance(item, dict) else None
        return enabled if isinstance(enabled, bool) else True

