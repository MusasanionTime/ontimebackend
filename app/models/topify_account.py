import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class TopifyAccount(Base):
    __tablename__ = "topify_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # These fields preserve Topify's documented reserve idempotency tuple
    # across retries after an uncertain provider response.
    request_email: Mapped[str] = mapped_column(String(255), nullable=False)
    request_name: Mapped[str] = mapped_column(String(200), nullable=False)
    request_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_code: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    account_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bank_code: Mapped[str] = mapped_column(String(20), default="30901", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="NGN", nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False, index=True
    )
    is_sandbox: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
