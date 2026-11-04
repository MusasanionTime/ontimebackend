from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AdminBigisubWalletResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    username: str
    email: str
    full_name: str
    balance: Decimal
    pending_amount: Decimal
    referal_balance: Decimal
    user_type: str
    reserved_account_number: str | None = None
    bank_name: str | None = None
    account_name: str | None = None


class AdminBigisubStatusResponse(BaseModel):
    provider: str
    status: str
    message: str
    wallet: AdminBigisubWalletResponse