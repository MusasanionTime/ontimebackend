import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class MonnifyAccount(Base):
    __tablename__ = "monnify_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    account_reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    reservation_reference: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        index=True,
    )

    account_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    account_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )

    bank_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    bank_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="NGN",
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(30),
        default="monnify",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )