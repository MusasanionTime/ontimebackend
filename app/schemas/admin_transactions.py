from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminTransactionListItem(BaseModel):
    id: UUID
    wallet_id: UUID

    user_id: UUID
    user_email: EmailStr
    user_first_name: str | None = None
    user_last_name: str | None = None

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

    model_config = {
        "from_attributes": True
    }


class AdminTransactionListResponse(BaseModel):
    items: list[AdminTransactionListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminTransactionDetailResponse(BaseModel):
    id: UUID

    wallet_id: UUID
    wallet_currency: str
    wallet_balance: Decimal
    wallet_status: str

    user_id: UUID
    user_email: EmailStr
    user_phone: str | None = None
    user_first_name: str | None = None
    user_last_name: str | None = None
    user_is_active: bool
    user_is_verified: bool

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

    model_config = {
        "from_attributes": True
    }