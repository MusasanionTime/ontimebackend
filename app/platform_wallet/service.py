import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Admin
from app.models.platform_wallet import PlatformTransaction, PlatformWallet


def get_or_create_platform_wallet(db: Session) -> PlatformWallet:
    wallet = db.scalar(select(PlatformWallet).with_for_update())
    if wallet:
        return wallet

    wallet = PlatformWallet(
        id=uuid.uuid4(),
        wallet_number="ADMIN-ONTIME-0001",
        currency="NGN",
        balance=Decimal("0.00"),
        status="active",
    )
    db.add(wallet)
    db.flush()
    return wallet


def credit_platform_wallet(
    db: Session,
    *,
    admin: Admin,
    amount: Decimal,
    reference: str,
    transaction_type: str,
    description: str | None = None,
) -> PlatformTransaction:
    if amount <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be greater than zero.")

    wallet = get_or_create_platform_wallet(db)
    if wallet.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Platform wallet is not active.")

    before = wallet.balance
    after = before + amount
    wallet.balance = after
    transaction = PlatformTransaction(
        platform_wallet_id=wallet.id,
        admin_id=admin.id,
        reference=reference,
        transaction_type=transaction_type,
        direction="credit",
        amount=amount,
        balance_before=before,
        balance_after=after,
        currency=wallet.currency,
        status="completed",
        description=description,
    )
    db.add(transaction)
    db.flush()
    return transaction


def debit_platform_wallet(
    db: Session,
    *,
    admin: Admin,
    amount: Decimal,
    reference: str,
    transaction_type: str,
    description: str | None = None,
) -> PlatformTransaction:
    if amount <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be greater than zero.")

    wallet = get_or_create_platform_wallet(db)
    if wallet.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Platform wallet is not active.")
    if wallet.balance < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient platform wallet balance.")

    before = wallet.balance
    after = before - amount
    wallet.balance = after
    transaction = PlatformTransaction(
        platform_wallet_id=wallet.id,
        admin_id=admin.id,
        reference=reference,
        transaction_type=transaction_type,
        direction="debit",
        amount=amount,
        balance_before=before,
        balance_after=after,
        currency=wallet.currency,
        status="completed",
        description=description,
    )
    db.add(transaction)
    db.flush()
    return transaction
