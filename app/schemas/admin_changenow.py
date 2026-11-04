from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminChangeNowExchangeListItem(BaseModel):
    id: UUID

    user_id: UUID
    user_email: EmailStr
    user_first_name: str | None = None
    user_last_name: str | None = None

    provider: str
    provider_transaction_id: str | None = None

    from_currency: str
    to_currency: str

    from_network: str | None = None
    to_network: str | None = None

    from_amount: Decimal
    to_amount: Decimal | None = None

    destination_address: str
    refund_address: str | None = None

    deposit_address: str | None = None
    deposit_extra_id: str | None = None

    status: str
    rate_id: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminChangeNowExchangeListResponse(BaseModel):
    items: list[AdminChangeNowExchangeListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminChangeNowExchangeStatusUpdate(BaseModel):
    status: str


class AdminChangeNowExchangeDetailResponse(BaseModel):
    id: UUID

    user_id: UUID
    user_email: EmailStr
    user_phone: str | None = None
    user_first_name: str | None = None
    user_last_name: str | None = None
    user_is_active: bool
    user_is_verified: bool

    provider: str
    provider_transaction_id: str | None = None

    from_currency: str
    to_currency: str

    from_network: str | None = None
    to_network: str | None = None

    from_amount: Decimal
    to_amount: Decimal | None = None

    destination_address: str
    refund_address: str | None = None

    deposit_address: str | None = None
    deposit_extra_id: str | None = None

    status: str
    rate_id: str | None = None

    provider_response: str | None = None

    created_at: datetime
    updated_at: datetime