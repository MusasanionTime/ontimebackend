from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    wallet_number: str
    currency: str
    balance: Decimal
    status: str
    created_at: datetime
    updated_at: datetime

    # Monnify virtual account
    account_number: str | None = None
    bank_name: str | None = None
    account_name: str | None = None


class TransactionResponse(BaseModel):
    id: UUID
    wallet_id: UUID
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