import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ReferralSetting(Base):
    __tablename__ = "referral_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reward_type: Mapped[str] = mapped_column(String(20), default="fixed", nullable=False)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    min_qualifying_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    reward_on_first_transaction: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    referral_code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    reward_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    reward_transaction_reference: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
