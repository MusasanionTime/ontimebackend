import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WithdrawalBankAccount(Base):
    __tablename__ = "withdrawal_bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    bank_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    bank_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    account_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    account_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="NGN",
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
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