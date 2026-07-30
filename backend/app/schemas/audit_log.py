from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AuditLogItemOut(BaseModel):
    """列表项：不含 detail，仅 has_detail 标记，供列表直读。"""

    id: int
    created_at: datetime

    actor_type: str = "user"
    actor_user_id: int | None = None
    actor_username: str | None = None

    source: str | None = None
    source_label: str | None = None
    category: str = ""
    category_label: str = ""
    action: str = Field(default="", max_length=96)
    action_label: str = ""

    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=64)
    target_name: str | None = Field(default=None, max_length=255)

    summary: str = ""
    ip: str | None = Field(default=None, max_length=64)
    success: bool = True
    error_message: str | None = Field(default=None, max_length=512)
    has_detail: bool = False


class AuditLogDetailOut(AuditLogItemOut):
    """详情项：额外携带完整 detail 文本。"""

    detail: str | None = None


class AuditLogListOut(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: list[AuditLogItemOut] = []
