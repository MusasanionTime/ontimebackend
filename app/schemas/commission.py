from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CommissionConfigurationUpdate(BaseModel):
    is_enabled: bool
    calculation_type: Literal["percentage", "fixed"] | None = None
    commission_value: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=6)
    calculation_basis: Literal["customer_purchase_amount"] | None = None
    minimum_commission: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    maximum_commission: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=2)
    effective_from: datetime | None = None
    reason: str = Field(min_length=5, max_length=500)


class CommissionConfigurationResponse(BaseModel):
    id: UUID
    service_key: str
    revision: int
    is_enabled: bool
    calculation_type: str | None
    commission_value: Decimal | None
    calculation_basis: str | None
    minimum_commission: Decimal | None
    maximum_commission: Decimal | None
    effective_from: datetime
    effective_until: datetime | None
    reason: str
    created_by_admin_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseCommissionItem(BaseModel):
    id: UUID
    reference: str
    customer_id: UUID
    customer_email: str | None = None
    customer_name: str | None = None
    source_transaction_id: UUID
    purchase_reference: str
    provider_reference: str | None = None
    configuration_id: UUID
    platform_transaction_id: UUID | None
    provider: str
    service_category: str
    purchase_amount: Decimal
    calculation_type: str
    calculation_value: Decimal
    calculation_basis: str
    commission_amount: Decimal
    currency: str
    status: str
    created_at: datetime


class PurchaseCommissionPage(BaseModel):
    items: list[PurchaseCommissionItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class CommissionReversalItem(BaseModel):
    id: UUID
    commission_id: UUID
    commission_reference: str
    purchase_reference: str
    customer_id: UUID
    customer_email: str | None = None
    reference: str
    refund_reference: str
    platform_transaction_id: UUID | None
    amount: Decimal
    status: str
    reason: str
    review_note: str | None
    created_at: datetime
    completed_at: datetime | None


class CommissionReversalPage(BaseModel):
    items: list[CommissionReversalItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class CommissionOverview(BaseModel):
    total_earned: Decimal
    total_reversed: Decimal
    net_total: Decimal
    today_earned: Decimal
    week_earned: Decimal
    month_earned: Decimal
    posted_count: int
    reversal_review_count: int
    pending_finalization_count: int
    by_service: list[dict]
    by_provider: list[dict]


class CommissionSummary(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    by_day: list[dict]
    by_service: list[dict]
    by_provider: list[dict]


class CommissionPurchaseReconciliation(BaseModel):
    transaction_id: UUID
    reference: str
    provider_reference: str | None
    provider: str | None
    service_category: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
