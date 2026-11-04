from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminWalletListItem(BaseModel):
    id: UUID
    user_id: UUID
    user_email: EmailStr
    user_first_name: str | None = None
    user_last_name: str | None = None
    wallet_number: str
    currency: str
    balance: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class AdminWalletListResponse(BaseModel):
    items: list[AdminWalletListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminWalletStatusUpdate(BaseModel):
    status: str
class AdminWalletAdjustment(BaseModel):
    amount: Decimal
    reference: str
    transaction_type: str = "admin_adjustment"
    description: str | None = None
