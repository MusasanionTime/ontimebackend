import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CommissionConfiguration(Base):
    """Immutable-by-revision commission policy history."""

    __tablename__ = "commission_configurations"
    __table_args__ = (
        UniqueConstraint("service_key", "revision", name="uq_commission_config_service_revision"),
        CheckConstraint("commission_value IS NULL OR commission_value > 0", name="ck_commission_config_value_positive"),
        CheckConstraint("minimum_commission IS NULL OR minimum_commission >= 0", name="ck_commission_config_min_nonnegative"),
        CheckConstraint("maximum_commission IS NULL OR maximum_commission >= 0", name="ck_commission_config_max_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    calculation_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    commission_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    calculation_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    minimum_commission: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    maximum_commission: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PurchaseCommission(Base):
    __tablename__ = "purchase_commissions"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_purchase_commissions_reference"),
        UniqueConstraint("source_transaction_id", name="uq_purchase_commissions_source_transaction"),
        UniqueConstraint("platform_transaction_id", name="uq_purchase_commissions_platform_transaction"),
        CheckConstraint("purchase_amount > 0", name="ck_purchase_commission_purchase_positive"),
        CheckConstraint("commission_amount > 0", name="ck_purchase_commission_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    configuration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commission_configurations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_transactions.id", ondelete="RESTRICT"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    service_category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    purchase_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    calculation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    calculation_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="posted", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class CommissionReversal(Base):
    __tablename__ = "commission_reversals"
    __table_args__ = (
        UniqueConstraint("commission_id", name="uq_commission_reversals_commission"),
        UniqueConstraint("reference", name="uq_commission_reversals_reference"),
        UniqueConstraint("platform_transaction_id", name="uq_commission_reversals_platform_transaction"),
        CheckConstraint("amount > 0", name="ck_commission_reversal_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    commission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_commissions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    refund_reference: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    platform_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_transactions.id", ondelete="RESTRICT"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_review", index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
