from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AdminUserWallet(BaseModel):
    id: UUID
    currency: str
    balance: Decimal
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class AdminUserTransaction(BaseModel):
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

    model_config = {
        "from_attributes": True
    }


class AdminUserDetailResponse(BaseModel):
    id: UUID
    email: EmailStr
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    wallet: AdminUserWallet | None = None
    transactions: list[AdminUserTransaction] = []