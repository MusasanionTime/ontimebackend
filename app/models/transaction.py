import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    transaction_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    balance_before: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="NGN",
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    provider_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )