from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, Field


class ReferralSummary(BaseModel):
    referral_code: str
    total_referrals: int
    rewarded_referrals: int
    total_earnings: Decimal


class ReferralItem(BaseModel):
    id: UUID
    referred_user_id: UUID
    referral_code: str
    reward_amount: Decimal
    reward_status: str
    reward_transaction_reference: str | None = None
    rewarded_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReferralSettingResponse(BaseModel):
    is_enabled: bool
    reward_type: str
    reward_amount: Decimal
    min_qualifying_amount: Decimal
    reward_on_first_transaction: bool


class ReferralSettingUpdate(BaseModel):
    is_enabled: bool | None = None
    reward_type: str | None = Field(default=None, pattern="^(fixed|percentage)$")
    reward_amount: Decimal | None = Field(default=None, ge=0)
    min_qualifying_amount: Decimal | None = Field(default=None, ge=0)
    reward_on_first_transaction: bool | None = None
