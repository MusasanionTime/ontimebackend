from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: "AdminResponse"


class AdminResponse(BaseModel):
    id: UUID
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
    }


AdminLoginResponse.model_rebuild()