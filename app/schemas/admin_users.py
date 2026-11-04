from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminUserListItem(BaseModel):
    id: UUID
    email: EmailStr
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminUserStatusUpdate(BaseModel):
    is_active: bool