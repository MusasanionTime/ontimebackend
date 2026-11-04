from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.wallet import TransactionResponse, WalletResponse
from app.wallet.service import WalletService


router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
)


@router.get(
    "",
    response_model=WalletResponse,
)
def get_wallet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wallet = db.scalar(
        select(Wallet).where(
            Wallet.user_id == current_user.id
        )
    )

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found.",
        )

    return WalletResponse(
        id=wallet.id,
        user_id=wallet.user_id,
        currency=wallet.currency,
        balance=wallet.balance,
        status=wallet.status,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
        wallet_number=wallet.wallet_number,
        account_number=None,
        bank_name=None,
        account_name=None,
    )


@router.get(
    "/transactions",
    response_model=list[TransactionResponse],
)
def get_wallet_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wallet = db.scalar(
        select(Wallet).where(
            Wallet.user_id == current_user.id
        )
    )

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found.",
        )

    return WalletService.get_transactions(
        db,
        wallet_id=wallet.id,
    )
