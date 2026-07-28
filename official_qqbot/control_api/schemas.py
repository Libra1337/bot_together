from pydantic import BaseModel, Field


class SeenUserRequest(BaseModel):
    user_key: str
    display_name: str = ""
    group_openid: str = ""


class EmailBindingRequest(BaseModel):
    user_key: str
    email: str


class ResourceLimitRequest(BaseModel):
    resource: str
    limit_count: int = Field(gt=0)
    window_unit: str
    updated_by: str = ""


class ResourceLimitCheckResponse(BaseModel):
    blocked: bool
    count: int
    limit: int
    window: int


class ResourceUsageRequest(BaseModel):
    resource: str
    user_key: str
    source_group_openid: str = ""
    message_id: str = ""


class CommandLogRequest(BaseModel):
    user_key: str = ""
    group_openid: str = ""
    command: str = ""
    content: str = ""
    message_id: str = ""


class OutboundLogRequest(BaseModel):
    user_key: str = ""
    group_openid: str = ""
    channel: str = ""
    status: str = ""
    content: str = ""
    message_id: str = ""


class RoleRequest(BaseModel):
    user_key: str
    role: str
    password: str = ""
    added_by: str = ""


class BanRequest(BaseModel):
    reason: str = ""
