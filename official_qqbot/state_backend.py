from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import shared_cooldown
from control_api.client import ControlApiClient


DATA_DIR = Path(__file__).resolve().parent / "data"


class LocalStateBackend:
    backend_name = "local"

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._admin_set: set[str] | None = None
        self._staff: dict[str, dict] | None = None
        self._staff_logged_in: set[str] | None = None
        self._banned_set: set[str] | None = None
        self._email_binds: dict[str, str] | None = None
        self._save_admins: Callable[[], None] | None = None
        self._save_staff: Callable[[], None] | None = None
        self._save_banned: Callable[[], None] | None = None
        self._save_email_binds: Callable[[], None] | None = None

    def bind_memory(
        self,
        admin_set: set[str],
        staff: dict[str, dict],
        staff_logged_in: set[str],
        banned_set: set[str],
        email_binds: dict[str, str],
        save_admins: Callable[[], None],
        save_staff: Callable[[], None],
        save_banned: Callable[[], None],
        save_email_binds: Callable[[], None],
    ) -> None:
        self._admin_set = admin_set
        self._staff = staff
        self._staff_logged_in = staff_logged_in
        self._banned_set = banned_set
        self._email_binds = email_binds
        self._save_admins = save_admins
        self._save_staff = save_staff
        self._save_banned = save_banned
        self._save_email_binds = save_email_binds

    def is_admin(self, user_key: str) -> bool:
        return user_key in self._admins()

    def is_admin_or_staff(self, user_key: str) -> bool:
        return self.is_admin(user_key) or user_key in self._staff_online()

    def is_banned(self, user_key: str) -> bool:
        return user_key in self._banned()

    def get_email_binding(self, user_key: str) -> str:
        return self._emails().get(user_key, "").strip()

    def set_email_binding(self, user_key: str, email: str) -> None:
        self._emails()[user_key] = email
        self._save_emails()

    def delete_email_binding(self, user_key: str) -> bool:
        if user_key not in self._emails():
            return False
        del self._emails()[user_key]
        self._save_emails()
        return True

    def add_admin(self, user_key: str) -> None:
        self._admins().add(user_key)
        self._save_admin_set()

    def remove_admin(self, user_key: str) -> bool:
        if user_key not in self._admins():
            return False
        self._admins().discard(user_key)
        self._save_admin_set()
        return True

    def staff_exists(self, user_key: str) -> bool:
        return user_key in self._staff_map()

    def get_staff_password(self, user_key: str) -> str:
        info = self._staff_map().get(user_key) or {}
        return str(info.get("password", ""))

    def set_staff_password(self, user_key: str, password: str) -> None:
        staff = self._staff_map()
        info = staff.setdefault(user_key, {})
        info["password"] = password
        self._save_staff_map()

    def login_staff(self, user_key: str) -> None:
        self._staff_online().add(user_key)

    def logout(self, user_key: str) -> bool:
        removed = self.remove_admin(user_key)
        if user_key in self._staff_online():
            self._staff_online().discard(user_key)
            removed = True
        return removed

    def add_staff(self, user_key: str, added_by: str = "") -> bool:
        if user_key in self._staff_map():
            return False
        self._staff_map()[user_key] = {"password": "", "added_by": added_by}
        self._save_staff_map()
        return True

    def delete_staff(self, user_key: str) -> bool:
        if user_key not in self._staff_map():
            return False
        del self._staff_map()[user_key]
        self._staff_online().discard(user_key)
        self._save_staff_map()
        return True

    def ban_user(self, user_key: str) -> None:
        self._banned().add(user_key)
        self._save_banned_set()

    def unban_user(self, user_key: str) -> bool:
        if user_key not in self._banned():
            return False
        self._banned().discard(user_key)
        self._save_banned_set()
        return True

    def counts(self) -> dict:
        return {
            "admins": len(self._admins()),
            "staff": len(self._staff_map()),
            "staff_online": len(self._staff_online()),
            "banned": len(self._banned()),
        }

    def set_resource_limit(self, feature: str, limit: int, unit: str, updated_by: str = "") -> None:
        shared_cooldown.set_restrict_rule(feature, limit, unit)

    def check_resource_limit(self, feature: str, user_key: str) -> tuple[bool, int, int, int]:
        return shared_cooldown.check_restrict_limit(feature, user_key)

    def get_resource_limit_status(self, feature: str, user_key: str) -> dict:
        return shared_cooldown.get_restrict_status(feature, user_key)

    def record_resource_usage(self, feature: str, user_key: str, ctx: dict | None = None) -> None:
        shared_cooldown.record_restrict_usage(feature, user_key)

    def reset_resource_usage(self) -> None:
        shared_cooldown.reset_restrict_usage()

    def list_resource_usage_stats(self) -> list[dict]:
        return shared_cooldown.get_restrict_usage_stats()

    def seen_user(self, user_key: str, display_name: str = "", group_openid: str = "") -> None:
        return None

    def log_command(
        self,
        user_key: str = "",
        group_openid: str = "",
        command: str = "",
        content: str = "",
        message_id: str = "",
    ) -> None:
        return None

    def log_outbound(
        self,
        user_key: str = "",
        group_openid: str = "",
        channel: str = "",
        status: str = "",
        content: str = "",
        message_id: str = "",
    ) -> None:
        return None

    def _admins(self) -> set[str]:
        if self._admin_set is not None:
            return self._admin_set
        return set(_read_json(self.data_dir / "admins.json", []))

    def _staff_map(self) -> dict[str, dict]:
        if self._staff is not None:
            return self._staff
        data = _read_json(self.data_dir / "staff.json", {})
        return data if isinstance(data, dict) else {}

    def _staff_online(self) -> set[str]:
        if self._staff_logged_in is not None:
            return self._staff_logged_in
        return set()

    def _banned(self) -> set[str]:
        if self._banned_set is not None:
            return self._banned_set
        return set(_read_json(self.data_dir / "banned.json", []))

    def _emails(self) -> dict[str, str]:
        if self._email_binds is not None:
            return self._email_binds
        data = _read_json(self.data_dir / "email_binds.json", {})
        return data if isinstance(data, dict) else {}

    def _save_admin_set(self) -> None:
        if self._save_admins:
            self._save_admins()
            return
        _write_json(self.data_dir / "admins.json", sorted(self._admins()))

    def _save_staff_map(self) -> None:
        if self._save_staff:
            self._save_staff()
            return
        _write_json(self.data_dir / "staff.json", self._staff_map())

    def _save_banned_set(self) -> None:
        if self._save_banned:
            self._save_banned()
            return
        _write_json(self.data_dir / "banned.json", sorted(self._banned()))

    def _save_emails(self) -> None:
        if self._save_email_binds:
            self._save_email_binds()
            return
        _write_json(self.data_dir / "email_binds.json", self._emails())


class CloudStateBackend:
    backend_name = "cloud"

    def __init__(self, client: ControlApiClient):
        self.client = client
        self._staff_logged_in: set[str] = set()

    def is_admin(self, user_key: str) -> bool:
        return bool(self.client.get_user_state(user_key).get("is_admin"))

    def is_admin_or_staff(self, user_key: str) -> bool:
        state = self.client.get_user_state(user_key)
        return bool(state.get("is_admin")) or user_key in self._staff_logged_in

    def is_banned(self, user_key: str) -> bool:
        return bool(self.client.get_user_state(user_key).get("is_banned"))

    def get_email_binding(self, user_key: str) -> str:
        return str(self.client.get_user_state(user_key).get("email") or "").strip()

    def set_email_binding(self, user_key: str, email: str) -> None:
        self.client.set_email_binding(user_key, email)

    def delete_email_binding(self, user_key: str) -> bool:
        self.client.delete_email_binding(user_key)
        return True

    def add_admin(self, user_key: str) -> None:
        self.client.add_role(user_key, "admin")

    def remove_admin(self, user_key: str) -> bool:
        self.client.delete_role(user_key, "admin")
        return True

    def staff_exists(self, user_key: str) -> bool:
        return "staff" in self.client.get_user_state(user_key).get("roles", [])

    def get_staff_password(self, user_key: str) -> str:
        return str(self.client.get_role(user_key, "staff").get("password") or "")

    def set_staff_password(self, user_key: str, password: str) -> None:
        self.client.add_role(user_key, "staff", password=password)

    def login_staff(self, user_key: str) -> None:
        self._staff_logged_in.add(user_key)

    def logout(self, user_key: str) -> bool:
        self.remove_admin(user_key)
        if user_key in self._staff_logged_in:
            self._staff_logged_in.discard(user_key)
            return True
        return True

    def add_staff(self, user_key: str, added_by: str = "") -> bool:
        self.client.add_role(user_key, "staff", added_by=added_by)
        return True

    def delete_staff(self, user_key: str) -> bool:
        self.client.delete_role(user_key, "staff")
        self._staff_logged_in.discard(user_key)
        return True

    def ban_user(self, user_key: str) -> None:
        self.client.set_banned(user_key, True)

    def unban_user(self, user_key: str) -> bool:
        self.client.set_banned(user_key, False)
        return True

    def counts(self) -> dict:
        return {"admins": 0, "staff": 0, "staff_online": len(self._staff_logged_in), "banned": 0}

    def set_resource_limit(self, feature: str, limit: int, unit: str, updated_by: str = "") -> None:
        self.client.set_resource_limit(feature, limit, unit, updated_by=updated_by)

    def check_resource_limit(self, feature: str, user_key: str) -> tuple[bool, int, int, int]:
        result = self.client.check_resource_limit(feature, user_key)
        return (
            bool(result.get("blocked")),
            int(result.get("count", 0)),
            int(result.get("limit", 0)),
            int(result.get("window", 0)),
        )

    def get_resource_limit_status(self, feature: str, user_key: str) -> dict:
        result = self.client.check_resource_limit(feature, user_key)
        return {
            "blocked": bool(result.get("blocked")),
            "count": int(result.get("count", 0)),
            "limit": int(result.get("limit", 0)),
            "window": int(result.get("window", 0)),
            "reset_after": int(result.get("reset_after", 0)),
        }

    def record_resource_usage(self, feature: str, user_key: str, ctx: dict | None = None) -> None:
        ctx = ctx or {}
        self.client.record_resource_usage(
            feature,
            user_key,
            source_group_openid=ctx.get("group_openid", ""),
            message_id=ctx.get("msg_id", ""),
        )

    def reset_resource_usage(self) -> None:
        self.client.reset_resource_usage()

    def list_resource_usage_stats(self) -> list[dict]:
        return list(self.client.list_resource_usage_stats().get("items", []))

    def seen_user(self, user_key: str, display_name: str = "", group_openid: str = "") -> None:
        self.client.seen_user(user_key, display_name=display_name, group_openid=group_openid)

    def log_command(
        self,
        user_key: str = "",
        group_openid: str = "",
        command: str = "",
        content: str = "",
        message_id: str = "",
    ) -> None:
        self.client.log_command(
            user_key=user_key,
            group_openid=group_openid,
            command=command,
            content=content,
            message_id=message_id,
        )

    def log_outbound(
        self,
        user_key: str = "",
        group_openid: str = "",
        channel: str = "",
        status: str = "",
        content: str = "",
        message_id: str = "",
    ) -> None:
        self.client.log_outbound(
            user_key=user_key,
            group_openid=group_openid,
            channel=channel,
            status=status,
            content=content,
            message_id=message_id,
        )


def build_state_backend(control_api_base_url: str, bot_token: str):
    if control_api_base_url:
        return CloudStateBackend(
            ControlApiClient(base_url=control_api_base_url, bot_token=bot_token)
        )
    return LocalStateBackend()


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
