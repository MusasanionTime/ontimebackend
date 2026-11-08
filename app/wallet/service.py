import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.referral.service import maybe_reward_first_qualifying_credit


class WalletService:

    @staticmethod
    def _existing_reference(
        db: Session,
        *,
        reference: str,
        wallet_id: uuid.UUID,
        amount: Decimal,
        transaction_type: str,
        direction: str,
    ) -> Transaction | None:
        existing = db.scalar(
            select(Transaction)
            .where(Transaction.reference == reference)
            .with_for_update()
        )
        if not existing:
            return None
        if (
            existing.wallet_id != wallet_id
            or existing.amount != amount
            or existing.transaction_type != transaction_type
            or existing.direction != direction
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transaction reference was already used for a different operation.",
            )
        return existing

    @staticmethod
    def credit(
        db: Session,
        *,
        wallet_id: uuid.UUID,
        amount: Decimal,
        reference: str,
        transaction_type: str = "deposit",
        provider: str | None = None,
        provider_reference: str | None = None,
        description: str | None = None,
    ) -> Transaction:

        if amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero.",
            )

        wallet = db.scalar(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
        )

        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found.",
            )

        existing = WalletService._existing_reference(
            db,
            reference=reference,
            wallet_id=wallet_id,
            amount=amount,
            transaction_type=transaction_type,
            direction="credit",
        )
        if existing:
            return existing

        balance_before = wallet.balance
        balance_after = balance_before + amount

        wallet.balance = balance_after

        transaction = Transaction(
            id=uuid.uuid4(),
            wallet_id=wallet.id,
            reference=reference,
            transaction_type=transaction_type,
            direction="credit",
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            currency=wallet.currency,
            status="completed",
            provider=provider,
            provider_reference=provider_reference,
            description=description,
        )

        db.add(transaction)
        db.flush()

        # Referral reward is evaluated only after a successful wallet credit.
        maybe_reward_first_qualifying_credit(
            db,
            referred_user_id=wallet.user_id,
            credited_amount=amount,
            transaction_type=transaction_type,
        )

        return transaction

    @staticmethod
    def debit(
        db: Session,
        *,
        wallet_id: uuid.UUID,
        amount: Decimal,
        reference: str,
        transaction_type: str = "withdrawal",
        provider: str | None = None,
        provider_reference: str | None = None,
        description: str | None = None,
    ) -> Transaction:

        if amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero.",
            )

        wallet = db.scalar(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
        )

        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found.",
            )

        balance_before = wallet.balance

        if balance_before < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient wallet balance.",
            )

        balance_after = balance_before - amount

        wallet.balance = balance_after

        transaction = Transaction(
            id=uuid.uuid4(),
            wallet_id=wallet.id,
            reference=reference,
            transaction_type=transaction_type,
            direction="debit",
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            currency=wallet.currency,
            status="completed",
            provider=provider,
            provider_reference=provider_reference,
            description=description,
        )

        db.add(transaction)

        return transaction

    @staticmethod
    def reserve_for_withdrawal(
        db: Session,
        *,
        wallet_id: uuid.UUID,
        amount: Decimal,
        reference: str,
        provider: str = "monnify",
        provider_reference: str | None = None,
        description: str | None = None,
    ) -> Transaction:

        if amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than zero.",
            )

        wallet = db.scalar(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
        )

        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found.",
            )

        if wallet.status.lower() != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is not active.",
            )

        balance_before = wallet.balance

        if balance_before < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient wallet balance.",
            )

        balance_after = balance_before - amount

        wallet.balance = balance_after

        transaction = Transaction(
            id=uuid.uuid4(),
            wallet_id=wallet.id,
            reference=reference,
            transaction_type="withdrawal",
            direction="debit",
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            currency=wallet.currency,
            status="pending",
            provider=provider,
            provider_reference=provider_reference,
            description=description
            or "Withdrawal initiated.",
        )

        db.add(transaction)

        return transaction

    @staticmethod
    def get_transactions(
        db: Session,
        *,
        wallet_id: uuid.UUID,
    ) -> list[Transaction]:

        wallet = db.scalar(
            select(Wallet).where(Wallet.id == wallet_id)
        )

        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found.",
            )

        return list(
            db.scalars(
                select(Transaction)
                .where(Transaction.wallet_id == wallet_id)
                .order_by(Transaction.created_at.desc())
            ).all()
        )
