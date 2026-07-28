import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from .db import create_app_engine, init_db
from .service import ControlService, RESTRICT_WINDOWS


def migrate_local_state(data_dir: str | Path, engine: Engine) -> dict:
    root = Path(data_dir)
    service = ControlService(engine)
    counts = {
        "admins": 0,
        "staff": 0,
        "banned": 0,
        "email_bindings": 0,
        "resource_limits": 0,
        "resource_usage": 0,
    }

    for user_key in _read_json(root / "admins.json", []):
        service.add_role(str(user_key), "admin", added_by="migration")
        counts["admins"] += 1

    staff_data = _read_json(root / "staff.json", {})
    if isinstance(staff_data, dict):
        for user_key, info in staff_data.items():
            password = ""
            added_by = "migration"
            if isinstance(info, dict):
                password = str(info.get("password", ""))
                added_by = str(info.get("added_by", "migration"))
            service.add_role(
                str(user_key), "staff", password=password, added_by=added_by
            )
            counts["staff"] += 1

    for user_key in _read_json(root / "banned.json", []):
        service.set_banned(str(user_key), True, reason="migrated local ban")
        counts["banned"] += 1

    email_data = _read_json(root / "email_binds.json", {})
    if isinstance(email_data, dict):
        for user_key, email in email_data.items():
            service.set_email_binding(str(user_key), str(email))
            counts["email_bindings"] += 1

    cooldowns = _read_json(root / "cooldowns.json", {})
    if isinstance(cooldowns, dict):
        counts["resource_limits"] += _migrate_restrict_rules(service, cooldowns)
        counts["resource_usage"] += _migrate_restrict_log(service, cooldowns)

    return counts


def _migrate_restrict_rules(service: ControlService, cooldowns: dict) -> int:
    count = 0
    rules = cooldowns.get("restrict_rules", {})
    if not isinstance(rules, dict):
        return 0
    for resource, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        unit = str(rule.get("unit") or _unit_from_window(rule.get("window")) or "")
        limit = int(rule.get("limit", 0) or 0)
        if not unit or limit <= 0:
            continue
        service.set_resource_limit(str(resource), limit, unit, updated_by="migration")
        count += 1
    return count


def _migrate_restrict_log(service: ControlService, cooldowns: dict) -> int:
    count = 0
    logs = cooldowns.get("restrict_log", {})
    if not isinstance(logs, dict):
        return 0
    for resource, user_logs in logs.items():
        if not isinstance(user_logs, dict):
            continue
        for user_key, timestamps in user_logs.items():
            if not isinstance(timestamps, list):
                continue
            for ts in timestamps:
                try:
                    used_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
                if service.resource_usage_exists(
                    str(resource), str(user_key), used_at
                ):
                    continue
                service.record_resource_usage(str(resource), str(user_key), used_at=used_at)
                count += 1
    return count


def _unit_from_window(window) -> str:
    try:
        seconds = int(window)
    except (TypeError, ValueError):
        return ""
    for unit, expected in RESTRICT_WINDOWS.items():
        if expected == seconds:
            return unit
    return ""


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> None:
    bot_root = Path(__file__).resolve().parent.parent
    data_dir = Path(os.getenv("LOCAL_STATE_DIR", str(bot_root / "data")))
    engine = create_app_engine(os.getenv("DATABASE_URL", ""))
    init_db(engine)
    counts = migrate_local_state(data_dir, engine)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
