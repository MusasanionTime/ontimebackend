from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminMonnifyAccountListItem(BaseModel):
    id: UUID
    user_id: UUID
    wallet_id: UUID

    user_email: EmailStr
    user_first_name: str | None = None
    user_last_name: str | None = None

    account_reference: str
    reservation_reference: str | None = None
    account_name: str
    account_number: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    currency: str
    status: str
    provider: str

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminMonnifyAccountListResponse(BaseModel):
    items: list[AdminMonnifyAccountListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminMonnifyAccountStatusUpdate(BaseModel):
    status: str


class AdminMonnifyTransaction(BaseModel):
    id: UUID
    reference: str
    transaction_type: str
    direction: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    currency: str
    status: str
    provider: str | None = None
    provider_reference: str | None = None
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminMonnifyAccountDetailResponse(BaseModel):
    id: UUID

    user_id: UUID
    user_email: EmailStr
    user_phone: str | None = None
    user_first_name: str | None = None
    user_last_name: str | None = None
    user_is_active: bool
    user_is_verified: bool

    wallet_id: UUID
    wallet_balance: Decimal
    wallet_currency: str
    wallet_status: str

    account_reference: str
    reservation_reference: str | None = None
    account_name: str
    account_number: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    currency: str
    status: str
    provider: str

    created_at: datetime
    updated_at: datetime

    transactions: list[AdminMonnifyTransaction] = []