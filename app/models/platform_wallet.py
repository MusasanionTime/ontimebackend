import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PlatformWallet(Base):
    __tablename__ = "platform_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="NGN", nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PlatformTransaction(Base):
    __tablename__ = "platform_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform_wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True, index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="NGN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
