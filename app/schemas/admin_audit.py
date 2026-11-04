from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminAuditLogListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    admin_id: UUID
    admin_email: str | None = None
    admin_first_name: str | None = None
    admin_last_name: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    description: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    extra_data: dict | None = None
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminAuditLogDetailResponse(AdminAuditLogListItem):
    pass