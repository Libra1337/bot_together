from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.engine import Engine

from .db import session_scope
from .models import (
    AuditLog,
    Announcement,
    CommandLog,
    EmailBinding,
    OutboundLog,
    ResourceLimitRule,
    ResourceUsage,
    Role,
    UpdatePackage,
    User,
    utc_now,
)


BEIJING_TZ = timezone(timedelta(hours=8))


def format_beijing_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ).strftime("%Y-%m-%d-%H:%M:%S")


RESTRICT_WINDOWS = {
    "min": 60,
    "hour": 3600,
    "day": 86400,
    "month": 30 * 86400,
    "quarter": 90 * 86400,
    "year": 365 * 86400,
}
RESOURCE_STATS_WINDOWS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "month": 30 * 86400,
    "year": 365 * 86400,
}
RESOURCE_NAMES = {"163", "4399", "nfa"}
ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"


class ControlService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def upsert_seen_user(
        self,
        user_key: str,
        display_name: str = "",
        group_openid: str = "",
    ) -> dict:
        user_key = self._clean_user_key(user_key)
        now = utc_now()
        with session_scope(self.engine) as session:
            user = session.scalar(select(User).where(User.user_key == user_key))
            if user is None:
                user = User(user_key=user_key, first_seen_at=now)
                session.add(user)
            if display_name:
                user.display_name = display_name
            if group_openid:
                user.last_group_openid = group_openid
            user.last_seen_at = now
            user.updated_at = now
            session.flush()
            return self._user_to_dict(user)

    def get_user_state(self, user_key: str) -> dict:
        user_key = self._clean_user_key(user_key)
        with session_scope(self.engine) as session:
            user = session.scalar(select(User).where(User.user_key == user_key))
            roles = [
                item.role
                for item in session.scalars(
                    select(Role).where(Role.user_key == user_key)
                ).all()
            ]
            binding = session.scalar(
                select(EmailBinding).where(EmailBinding.user_key == user_key)
            )
            return {
                "user_key": user_key,
                "email": binding.email if binding else "",
                "roles": roles,
                "is_admin": ROLE_ADMIN in roles,
                "is_staff": ROLE_STAFF in roles,
                "is_banned": bool(user.is_banned) if user else False,
                "display_name": user.display_name if user else "",
                "last_group_openid": user.last_group_openid if user else "",
            }

    def set_email_binding(self, user_key: str, email: str) -> str:
        user_key = self._clean_user_key(user_key)
        email = str(email).strip()
        now = utc_now()
        with session_scope(self.engine) as session:
            self._ensure_user(session, user_key, now)
            binding = session.scalar(
                select(EmailBinding).where(EmailBinding.user_key == user_key)
            )
            if binding is None:
                binding = EmailBinding(user_key=user_key, email=email, created_at=now)
                session.add(binding)
            binding.email = email
            binding.updated_at = now
        return email

    def get_email_binding(self, user_key: str) -> str:
        user_key = self._clean_user_key(user_key)
        with session_scope(self.engine) as session:
            binding = session.scalar(
                select(EmailBinding).where(EmailBinding.user_key == user_key)
            )
            return binding.email if binding else ""

    def delete_email_binding(self, user_key: str) -> None:
        user_key = self._clean_user_key(user_key)
        with session_scope(self.engine) as session:
            session.execute(delete(EmailBinding).where(EmailBinding.user_key == user_key))

    def add_role(
        self,
        user_key: str,
        role: str,
        password: str = "",
        added_by: str = "",
    ) -> None:
        user_key = self._clean_user_key(user_key)
        role = self._clean_role(role)
        now = utc_now()
        with session_scope(self.engine) as session:
            self._ensure_user(session, user_key, now)
            item = session.scalar(
                select(Role).where(Role.user_key == user_key, Role.role == role)
            )
            if item is None:
                item = Role(user_key=user_key, role=role, created_at=now)
                session.add(item)
            item.password = password
            item.added_by = added_by
            item.updated_at = now

    def revoke_role(self, user_key: str, role: str) -> None:
        user_key = self._clean_user_key(user_key)
        role = self._clean_role(role)
        with session_scope(self.engine) as session:
            session.execute(
                delete(Role).where(Role.user_key == user_key, Role.role == role)
            )

    def list_roles(self, role: str | None = None) -> list[dict]:
        with session_scope(self.engine) as session:
            stmt = select(Role)
            if role:
                stmt = stmt.where(Role.role == self._clean_role(role))
            rows = session.scalars(stmt.order_by(Role.created_at.desc())).all()
            return [
                {
                    "user_key": item.user_key,
                    "role": item.role,
                    "password": item.password,
                    "added_by": item.added_by or "",
                }
                for item in rows
            ]

    def get_role(self, user_key: str, role: str) -> dict | None:
        user_key = self._clean_user_key(user_key)
        role = self._clean_role(role)
        with session_scope(self.engine) as session:
            item = session.scalar(
                select(Role).where(Role.user_key == user_key, Role.role == role)
            )
            if item is None:
                return None
            return {
                "user_key": item.user_key,
                "role": item.role,
                "password": item.password,
                "added_by": item.added_by or "",
            }

    def is_banned(self, user_key: str) -> bool:
        user_key = self._clean_user_key(user_key)
        with session_scope(self.engine) as session:
            user = session.scalar(select(User).where(User.user_key == user_key))
            return bool(user and user.is_banned)

    def set_banned(
        self, user_key: str, banned: bool, reason: str = "", updated_by: str = ""
    ) -> None:
        user_key = self._clean_user_key(user_key)
        now = utc_now()
        with session_scope(self.engine) as session:
            user = session.scalar(select(User).where(User.user_key == user_key))
            if user is None:
                user = User(user_key=user_key, first_seen_at=now, last_seen_at=now)
                session.add(user)
            user.is_banned = bool(banned)
            user.banned_reason = reason if banned else ""
            user.updated_at = now
            session.add(
                AuditLog(
                    actor_user_key=updated_by,
                    action="ban" if banned else "unban",
                    target_user_key=user_key,
                    detail=reason,
                )
            )

    def set_resource_limit(
        self, resource: str, limit_count: int, window_unit: str, updated_by: str = ""
    ) -> dict:
        resource = self._clean_resource(resource)
        window_unit = self._clean_window_unit(window_unit)
        limit_count = int(limit_count)
        if limit_count <= 0:
            raise ValueError("limit_count must be greater than zero")
        now = utc_now()
        with session_scope(self.engine) as session:
            rule = session.scalar(
                select(ResourceLimitRule).where(
                    ResourceLimitRule.resource == resource
                )
            )
            if rule is None:
                rule = ResourceLimitRule(resource=resource, created_at=now)
                session.add(rule)
            rule.limit_count = limit_count
            rule.window_unit = window_unit
            rule.window_seconds = RESTRICT_WINDOWS[window_unit]
            rule.updated_by = updated_by
            rule.updated_at = now
            session.flush()
            return self._rule_to_dict(rule)

    def get_resource_limit(self, resource: str) -> dict | None:
        resource = self._clean_resource(resource)
        with session_scope(self.engine) as session:
            rule = session.scalar(
                select(ResourceLimitRule).where(
                    ResourceLimitRule.resource == resource
                )
            )
            return self._rule_to_dict(rule) if rule else None

    def list_resource_limits(self) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(ResourceLimitRule).order_by(ResourceLimitRule.resource)
            ).all()
            return [self._rule_to_dict(row) for row in rows]

    def check_resource_limit(self, resource: str, user_key: str) -> tuple[bool, int, int, int]:
        status = self.get_resource_limit_status(resource, user_key)
        return (
            bool(status["blocked"]),
            int(status["count"]),
            int(status["limit"]),
            int(status["window"]),
        )

    def get_resource_limit_status(
        self, resource: str, user_key: str, now: datetime | None = None
    ) -> dict:
        resource = self._clean_resource(resource)
        user_key = self._clean_user_key(user_key)
        now = now or utc_now()
        with session_scope(self.engine) as session:
            rule = session.scalar(
                select(ResourceLimitRule).where(
                    ResourceLimitRule.resource == resource
                )
            )
            if rule is None:
                return {
                    "blocked": False,
                    "count": 0,
                    "limit": 0,
                    "window": 0,
                    "reset_after": 0,
                }
            cutoff = now - timedelta(seconds=int(rule.window_seconds))
            used_rows = session.scalars(
                select(ResourceUsage.used_at).where(
                    ResourceUsage.resource == resource,
                    ResourceUsage.user_key == user_key,
                    ResourceUsage.used_at >= cutoff,
                )
            ).all()
            count = len(used_rows)
            reset_after = 0
            if used_rows:
                oldest = min(self._aware_utc(value) for value in used_rows)
                reset_at = oldest + timedelta(seconds=int(rule.window_seconds))
                reset_after = max(0, int((reset_at - self._aware_utc(now)).total_seconds()))
            return {
                "blocked": count >= int(rule.limit_count),
                "count": count,
                "limit": int(rule.limit_count),
                "window": int(rule.window_seconds),
                "reset_after": reset_after,
            }

    def list_resource_usage_stats(self, now: datetime | None = None) -> list[dict]:
        now = self._aware_utc(now or utc_now())
        limits = {row["resource"]: row for row in self.list_resource_limits()}
        with session_scope(self.engine) as session:
            rows = session.execute(select(
                ResourceUsage.resource,
                *[func.sum(case((ResourceUsage.used_at >= now - timedelta(seconds=seconds), 1), else_=0)).label(key)
                  for key, seconds in RESOURCE_STATS_WINDOWS.items()],
            ).where(
                ResourceUsage.used_at >= now - timedelta(days=365),
                ResourceUsage.used_at <= now,
            ).group_by(ResourceUsage.resource)).mappings().all()
        counts_by_resource = {row["resource"]: row for row in rows}
        return [{
            "resource": resource,
            "limit_count": int(limits.get(resource, {}).get("limit_count", 0)),
            "window_unit": limits.get(resource, {}).get("window_unit", ""),
            "window_seconds": int(limits.get(resource, {}).get("window_seconds", 0)),
            "counts": {key: int(counts_by_resource.get(resource, {}).get(key, 0) or 0)
                       for key in RESOURCE_STATS_WINDOWS},
        } for resource in sorted(RESOURCE_NAMES)]

    def list_resource_user_usage(self, *, resource: str = "", query: str = "",
                                 page: int = 1, page_size: int = 20,
                                 now: datetime | None = None) -> dict:
        """Aggregate each user's own rolling quota, with bounded SQL pagination."""
        now = self._aware_utc(now or utc_now())
        rules = {item["resource"]: item for item in self.list_resource_limits()}
        selected = [item for name, item in rules.items() if not resource or name == resource]
        page_size = min(100, max(1, int(page_size)))
        if not selected:
            return {"items": [], "total": 0, "page": 1, "pages": 1}
        window_filter = or_(*[and_(
            ResourceUsage.resource == item["resource"],
            ResourceUsage.used_at >= now - timedelta(seconds=item["window_seconds"]),
        ) for item in selected])
        grouped = select(
            ResourceUsage.resource, ResourceUsage.user_key,
            func.count(ResourceUsage.id).label("used"),
            func.min(ResourceUsage.used_at).label("oldest"),
            func.max(ResourceUsage.used_at).label("latest"),
        ).where(window_filter, ResourceUsage.used_at <= now)
        if query:
            grouped = grouped.where(ResourceUsage.user_key.contains(query, autoescape=True))
        grouped = grouped.group_by(ResourceUsage.resource, ResourceUsage.user_key).subquery()
        with session_scope(self.engine) as session:
            total = session.scalar(select(func.count()).select_from(grouped)) or 0
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(pages, max(1, int(page)))
            rows = session.execute(select(grouped).order_by(
                grouped.c.used.desc(), grouped.c.resource, grouped.c.user_key,
            ).offset((page - 1) * page_size).limit(page_size)).mappings().all()
        items = []
        for row in rows:
            rule = rules[row["resource"]]
            reset_at = self._aware_utc(row["oldest"]) + timedelta(seconds=rule["window_seconds"])
            items.append({
                "resource": row["resource"], "user_key": row["user_key"],
                "used": int(row["used"]), "limit": rule["limit_count"],
                "remaining": max(0, rule["limit_count"] - row["used"]),
                "blocked": row["used"] >= rule["limit_count"],
                "window_unit": rule["window_unit"],
                "reset_after": max(0, int((reset_at - now).total_seconds())),
                "latest": format_beijing_datetime(row["latest"]),
            })
        return {"items": items, "total": total, "page": page, "pages": pages}

    def record_resource_usage(
        self,
        resource: str,
        user_key: str,
        source_group_openid: str = "",
        message_id: str = "",
        used_at: datetime | None = None,
    ) -> None:
        resource = self._clean_resource(resource)
        user_key = self._clean_user_key(user_key)
        now = used_at or utc_now()
        with session_scope(self.engine) as session:
            self._ensure_user(session, user_key, now)
            session.add(
                ResourceUsage(
                    resource=resource,
                    user_key=user_key,
                    used_at=now,
                    source_group_openid=source_group_openid,
                    message_id=message_id,
                )
            )

    def resource_usage_exists(
        self,
        resource: str,
        user_key: str,
        used_at: datetime,
    ) -> bool:
        resource = self._clean_resource(resource)
        user_key = self._clean_user_key(user_key)
        with session_scope(self.engine) as session:
            found = session.scalar(
                select(ResourceUsage.id).where(
                    ResourceUsage.resource == resource,
                    ResourceUsage.user_key == user_key,
                    ResourceUsage.used_at == used_at,
                )
            )
            return found is not None

    def reset_resource_usage(self, resource: str | None = None) -> None:
        with session_scope(self.engine) as session:
            stmt = delete(ResourceUsage)
            if resource:
                stmt = stmt.where(ResourceUsage.resource == self._clean_resource(resource))
            session.execute(stmt)

    def log_command(
        self,
        user_key: str = "",
        group_openid: str = "",
        command: str = "",
        content: str = "",
        message_id: str = "",
    ) -> None:
        with session_scope(self.engine) as session:
            session.add(
                CommandLog(
                    user_key=user_key,
                    group_openid=group_openid,
                    command=command,
                    content=content,
                    message_id=message_id,
                )
            )

    def log_audit(
        self,
        action: str,
        actor_user_key: str = "",
        target_user_key: str = "",
        detail: str = "",
    ) -> None:
        with session_scope(self.engine) as session:
            session.add(
                AuditLog(
                    actor_user_key=actor_user_key,
                    action=action,
                    target_user_key=target_user_key,
                    detail=detail,
                )
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
        with session_scope(self.engine) as session:
            session.add(
                OutboundLog(
                    user_key=user_key,
                    group_openid=group_openid,
                    channel=channel,
                    status=status,
                    content=content,
                    message_id=message_id,
                )
            )

    def list_users(self, limit: int | None = 100) -> list[dict]:
        with session_scope(self.engine) as session:
            query = select(User).order_by(User.last_seen_at.desc())
            if limit is not None:
                query = query.limit(limit)
            rows = session.scalars(query).all()
            return [self._user_to_dict(row) for row in rows]

    def list_command_logs(self, limit: int = 100) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(select(CommandLog).order_by(CommandLog.created_at.desc()).limit(limit)).all()
            return [
                {
                    "user_key": row.user_key or "",
                    "group_openid": row.group_openid or "",
                    "command": row.command or "",
                    "content": row.content or "",
                    "message_id": row.message_id or "",
                    "created_at": format_beijing_datetime(row.created_at),
                }
                for row in rows
            ]

    def list_audit_logs(self, limit: int = 100) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
            return [
                {
                    "actor_user_key": row.actor_user_key or "",
                    "action": row.action,
                    "target_user_key": row.target_user_key or "",
                    "detail": row.detail or "",
                    "created_at": format_beijing_datetime(row.created_at),
                }
                for row in rows
            ]

    def list_outbound_logs(self, limit: int = 100) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(select(OutboundLog).order_by(OutboundLog.created_at.desc()).limit(limit)).all()
            return [
                {
                    "user_key": row.user_key or "",
                    "group_openid": row.group_openid or "",
                    "channel": row.channel or "",
                    "status": row.status or "",
                    "content": row.content or "",
                    "message_id": row.message_id or "",
                    "created_at": format_beijing_datetime(row.created_at),
                }
                for row in rows
            ]

    def create_announcement(
        self,
        source: str,
        title: str,
        body: str,
        link_text: str = "",
        link_url: str = "",
        is_public: bool = True,
        created_by: str = "dashboard",
    ) -> dict:
        now = utc_now()
        with session_scope(self.engine) as session:
            item = Announcement(
                source=str(source or "Miracle").strip() or "Miracle",
                title=str(title or "").strip(),
                body=str(body or "").strip(),
                link_text=str(link_text or "").strip(),
                link_url=str(link_url or "").strip(),
                is_public=bool(is_public),
                created_by=str(created_by or "dashboard"),
                created_at=now,
                updated_at=now,
            )
            if not item.title or not item.body:
                raise ValueError("announcement title and body are required")
            session.add(item)
            session.flush()
            return self._announcement_to_dict(item)

    def list_announcements(self, limit: int = 50) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(Announcement).order_by(Announcement.created_at.desc()).limit(limit)
            ).all()
            return [self._announcement_to_dict(row) for row in rows]

    def set_announcement_public(self, announcement_id: int, is_public: bool) -> None:
        with session_scope(self.engine) as session:
            item = session.get(Announcement, int(announcement_id))
            if item is None:
                return
            item.is_public = bool(is_public)
            item.updated_at = utc_now()

    def create_update_package(
        self,
        version: str,
        title: str,
        body: str,
        is_public: bool = True,
        created_by: str = "dashboard",
    ) -> dict:
        now = utc_now()
        with session_scope(self.engine) as session:
            item = UpdatePackage(
                version=str(version or "").strip(),
                title=str(title or "").strip(),
                body=str(body or "").strip(),
                is_public=bool(is_public),
                created_by=str(created_by or "dashboard"),
                created_at=now,
                updated_at=now,
            )
            if not item.version or not item.title:
                raise ValueError("update version and title are required")
            session.add(item)
            session.flush()
            return self._update_package_to_dict(item)

    def list_update_packages(self, limit: int = 50) -> list[dict]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(UpdatePackage).order_by(UpdatePackage.created_at.desc()).limit(limit)
            ).all()
            return [self._update_package_to_dict(row) for row in rows]

    @staticmethod
    def _utc_cutoff(window_seconds: int) -> datetime:
        return utc_now() - timedelta(seconds=int(window_seconds))

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _clean_user_key(user_key: str) -> str:
        value = str(user_key or "").strip()
        if not value:
            raise ValueError("user_key is required")
        return value

    @staticmethod
    def _clean_resource(resource: str) -> str:
        value = str(resource or "").strip().lower()
        if value not in RESOURCE_NAMES:
            raise ValueError("invalid resource")
        return value

    @staticmethod
    def _clean_window_unit(window_unit: str) -> str:
        value = str(window_unit or "").strip().lower()
        if value not in RESTRICT_WINDOWS:
            raise ValueError("invalid window_unit")
        return value

    @staticmethod
    def _clean_role(role: str) -> str:
        value = str(role or "").strip().lower()
        if value not in {ROLE_ADMIN, ROLE_STAFF}:
            raise ValueError("invalid role")
        return value

    @staticmethod
    def _rule_to_dict(rule: ResourceLimitRule) -> dict:
        return {
            "resource": rule.resource,
            "limit_count": int(rule.limit_count),
            "window_unit": rule.window_unit,
            "window_seconds": int(rule.window_seconds),
            "updated_by": rule.updated_by or "",
        }

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        return {
            "user_key": user.user_key,
            "display_name": user.display_name or "",
            "last_group_openid": user.last_group_openid or "",
            "is_banned": bool(user.is_banned),
            "banned_reason": user.banned_reason or "",
            "first_seen_at": format_beijing_datetime(user.first_seen_at),
            "last_seen_at": format_beijing_datetime(user.last_seen_at),
        }

    @staticmethod
    def _ensure_user(session, user_key: str, now: datetime) -> User:
        user = session.scalar(select(User).where(User.user_key == user_key))
        if user is None:
            user = User(user_key=user_key, first_seen_at=now, last_seen_at=now)
            session.add(user)
        user.last_seen_at = now
        user.updated_at = now
        return user

    @staticmethod
    def _announcement_to_dict(item: Announcement) -> dict:
        return {
            "id": int(item.id),
            "source": item.source,
            "title": item.title,
            "body": item.body,
            "link_text": item.link_text or "",
            "link_url": item.link_url or "",
            "is_public": bool(item.is_public),
            "created_by": item.created_by or "",
            "created_at": format_beijing_datetime(item.created_at),
        }

    @staticmethod
    def _update_package_to_dict(item: UpdatePackage) -> dict:
        return {
            "id": int(item.id),
            "version": item.version,
            "title": item.title,
            "body": item.body,
            "is_public": bool(item.is_public),
            "created_by": item.created_by or "",
            "created_at": format_beijing_datetime(item.created_at),
        }
