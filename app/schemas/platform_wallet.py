from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, Field


class PlatformWalletResponse(BaseModel):
    id: UUID
    wallet_number: str
    currency: str
    balance: Decimal
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformWalletTransaction(BaseModel):
    id: UUID
    reference: str
    transaction_type: str
    direction: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    currency: str
    status: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformWalletAdjustment(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: str = Field(min_length=3, max_length=100)
    transaction_type: str = Field(min_length=3, max_length=40)
    description: str | None = None
