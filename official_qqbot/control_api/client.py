import httpx


class ControlApiClient:
    def __init__(
        self,
        base_url: str,
        bot_token: str,
        timeout: float = 8.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.bot_token = bot_token
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"X-Bot-Token": bot_token},
        )

    def close(self) -> None:
        self._client.close()

    def get_user_state(self, user_key: str) -> dict:
        return self._request("GET", f"/internal/users/{user_key}/state")

    def seen_user(
        self, user_key: str, display_name: str = "", group_openid: str = ""
    ) -> dict:
        return self._request(
            "POST",
            "/internal/events/seen",
            json={
                "user_key": user_key,
                "display_name": display_name,
                "group_openid": group_openid,
            },
        )

    def set_email_binding(self, user_key: str, email: str) -> dict:
        return self._request(
            "POST",
            "/internal/email-bindings",
            json={"user_key": user_key, "email": email},
        )

    def delete_email_binding(self, user_key: str) -> dict:
        return self._request("DELETE", f"/internal/email-bindings/{user_key}")

    def check_resource_limit(self, resource: str, user_key: str) -> dict:
        return self._request(
            "GET",
            f"/internal/resource-limits/{resource}/check",
            params={"user_key": user_key},
        )

    def list_resource_usage_stats(self) -> dict:
        return self._request("GET", "/internal/resource-usage/stats")

    def record_resource_usage(
        self,
        resource: str,
        user_key: str,
        source_group_openid: str = "",
        message_id: str = "",
    ) -> dict:
        return self._request(
            "POST",
            "/internal/resource-usage",
            json={
                "resource": resource,
                "user_key": user_key,
                "source_group_openid": source_group_openid,
                "message_id": message_id,
            },
        )

    def set_resource_limit(
        self, resource: str, limit_count: int, window_unit: str, updated_by: str = ""
    ) -> dict:
        return self._request(
            "POST",
            "/internal/resource-limits",
            json={
                "resource": resource,
                "limit_count": limit_count,
                "window_unit": window_unit,
                "updated_by": updated_by,
            },
        )

    def reset_resource_usage(self) -> dict:
        return self._request("POST", "/internal/resource-limits/reset-usage")

    def log_command(
        self,
        user_key: str = "",
        group_openid: str = "",
        command: str = "",
        content: str = "",
        message_id: str = "",
    ) -> dict:
        return self._request(
            "POST",
            "/internal/logs/command",
            json={
                "user_key": user_key,
                "group_openid": group_openid,
                "command": command,
                "content": content,
                "message_id": message_id,
            },
        )

    def log_outbound(
        self,
        user_key: str = "",
        group_openid: str = "",
        channel: str = "",
        status: str = "",
        content: str = "",
        message_id: str = "",
    ) -> dict:
        return self._request(
            "POST",
            "/internal/logs/outbound",
            json={
                "user_key": user_key,
                "group_openid": group_openid,
                "channel": channel,
                "status": status,
                "content": content,
                "message_id": message_id,
            },
        )

    def set_banned(self, user_key: str, banned: bool, reason: str = "") -> dict:
        route = "ban" if banned else "unban"
        return self._request(
            "POST",
            f"/internal/users/{user_key}/{route}",
            json={"reason": reason},
        )

    def add_role(
        self, user_key: str, role: str, password: str = "", added_by: str = ""
    ) -> dict:
        return self._request(
            "POST",
            "/internal/roles",
            json={
                "user_key": user_key,
                "role": role,
                "password": password,
                "added_by": added_by,
            },
        )

    def get_role(self, user_key: str, role: str) -> dict:
        return self._request("GET", f"/internal/roles/{role}/{user_key}")

    def delete_role(self, user_key: str, role: str) -> dict:
        return self._request("DELETE", f"/internal/roles/{role}/{user_key}")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()
