from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_key = Column(String(128), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    last_group_openid = Column(String(128), nullable=True)
    is_banned = Column(Boolean, nullable=False, default=False)
    banned_reason = Column(Text, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class EmailBinding(Base):
    __tablename__ = "email_bindings"

    id = Column(Integer, primary_key=True)
    user_key = Column(String(128), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("user_key", "role", name="uq_roles_user_role"),)

    id = Column(Integer, primary_key=True)
    user_key = Column(String(128), nullable=False, index=True)
    role = Column(String(32), nullable=False, index=True)
    password = Column(String(255), nullable=False, default="")
    added_by = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ResourceLimitRule(Base):
    __tablename__ = "resource_limit_rules"

    id = Column(Integer, primary_key=True)
    resource = Column(String(32), nullable=False, unique=True, index=True)
    limit_count = Column(Integer, nullable=False)
    window_unit = Column(String(32), nullable=False)
    window_seconds = Column(Integer, nullable=False)
    updated_by = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ResourceUsage(Base):
    __tablename__ = "resource_usage"

    id = Column(Integer, primary_key=True)
    resource = Column(String(32), nullable=False, index=True)
    user_key = Column(String(128), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    source_group_openid = Column(String(128), nullable=True)
    message_id = Column(String(128), nullable=True)


class CommandLog(Base):
    __tablename__ = "command_logs"

    id = Column(Integer, primary_key=True)
    user_key = Column(String(128), nullable=True, index=True)
    group_openid = Column(String(128), nullable=True, index=True)
    command = Column(String(128), nullable=True)
    content = Column(Text, nullable=True)
    message_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_user_key = Column(String(128), nullable=True, index=True)
    action = Column(String(128), nullable=False)
    target_user_key = Column(String(128), nullable=True, index=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class OutboundLog(Base):
    __tablename__ = "outbound_logs"

    id = Column(Integer, primary_key=True)
    user_key = Column(String(128), nullable=True, index=True)
    group_openid = Column(String(128), nullable=True, index=True)
    channel = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    content = Column(Text, nullable=True)
    message_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    source = Column(String(128), nullable=False, default="Miracle")
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    link_text = Column(String(128), nullable=False, default="")
    link_url = Column(String(512), nullable=False, default="")
    is_public = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(128), nullable=False, default="dashboard")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class UpdatePackage(Base):
    __tablename__ = "update_packages"

    id = Column(Integer, primary_key=True)
    version = Column(String(128), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    is_public = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(128), nullable=False, default="dashboard")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
