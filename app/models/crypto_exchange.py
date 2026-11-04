import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CryptoExchange(Base):
    __tablename__ = "crypto_exchanges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="changenow",
    )

    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
    )

    from_currency: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    to_currency: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    from_network: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    to_network: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    from_amount: Mapped[float] = mapped_column(
        Numeric(30, 18),
        nullable=False,
    )

    to_amount: Mapped[float | None] = mapped_column(
        Numeric(30, 18),
        nullable=True,
    )

    destination_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    refund_address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    deposit_address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    deposit_extra_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="waiting",
        index=True,
    )

    rate_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    provider_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )