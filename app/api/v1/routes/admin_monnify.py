from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.database.database import get_db
from app.models.admin import Admin
from app.models.monnify_account import MonnifyAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.admin_monnify import (
    AdminMonnifyAccountDetailResponse,
    AdminMonnifyAccountListItem,
    AdminMonnifyAccountListResponse,
    AdminMonnifyAccountStatusUpdate,
    AdminMonnifyTransaction,
)


router = APIRouter(
    prefix="/admin/monnify",
    tags=["Admin Monnify"],
)


@router.get(
    "/accounts",
    response_model=AdminMonnifyAccountListResponse,
)
def list_monnify_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status_filter: str | None = Query(None),
    user_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    query = (
        select(MonnifyAccount, User)
        .join(User, User.id == MonnifyAccount.user_id)
    )

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            or_(
                MonnifyAccount.account_reference.ilike(search_term),
                MonnifyAccount.reservation_reference.ilike(search_term),
                MonnifyAccount.account_name.ilike(search_term),
                MonnifyAccount.account_number.ilike(search_term),
                MonnifyAccount.bank_name.ilike(search_term),
                User.email.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term),
            )
        )

    if status_filter:
        query = query.where(
            MonnifyAccount.status == status_filter
        )

    if user_id:
        query = query.where(
            MonnifyAccount.user_id == user_id
        )

    count_query = select(func.count()).select_from(
        query.subquery()
    )

    total = db.scalar(count_query) or 0

    total_pages = ceil(total / page_size) if total else 0

    offset = (page - 1) * page_size

    rows = db.execute(
        query
        .order_by(MonnifyAccount.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    items = [
        AdminMonnifyAccountListItem(
            id=account.id,
            user_id=account.user_id,
            wallet_id=account.wallet_id,
            user_email=user.email,
            user_first_name=user.first_name,
            user_last_name=user.last_name,
            account_reference=account.account_reference,
            reservation_reference=account.reservation_reference,
            account_name=account.account_name,
            account_number=account.account_number,
            bank_name=account.bank_name,
            bank_code=account.bank_code,
            currency=account.currency,
            status=account.status,
            provider=account.provider,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
        for account, user in rows
    ]

    return AdminMonnifyAccountListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/accounts/{account_id}",
    response_model=AdminMonnifyAccountDetailResponse,
)
def get_monnify_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    account = db.scalar(
        select(MonnifyAccount).where(
            MonnifyAccount.id == account_id
        )
    )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monnify account not found",
        )

    user = db.scalar(
        select(User).where(User.id == account.user_id)
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account owner not found",
        )

    wallet = db.scalar(
        select(Wallet).where(Wallet.id == account.wallet_id)
    )

    transactions = db.scalars(
        select(Transaction)
        .where(Transaction.wallet_id == account.wallet_id)
        .order_by(Transaction.created_at.desc())
    ).all()

    transaction_items = [
        AdminMonnifyTransaction(
            id=transaction.id,
            reference=transaction.reference,
            transaction_type=transaction.transaction_type,
            direction=transaction.direction,
            amount=transaction.amount,
            balance_before=transaction.balance_before,
            balance_after=transaction.balance_after,
            currency=transaction.currency,
            status=transaction.status,
            provider=transaction.provider,
            provider_reference=transaction.provider_reference,
            description=transaction.description,
            created_at=transaction.created_at,
        )
        for transaction in transactions
    ]

    return AdminMonnifyAccountDetailResponse(
        id=account.id,

        user_id=user.id,
        user_email=user.email,
        user_phone=user.phone,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        user_is_active=user.is_active,
        user_is_verified=user.is_verified,

        wallet_id=account.wallet_id,
        wallet_balance=wallet.balance if wallet else 0,
        wallet_currency=wallet.currency if wallet else account.currency,
        wallet_status=wallet.status if wallet else "unknown",

        account_reference=account.account_reference,
        reservation_reference=account.reservation_reference,
        account_name=account.account_name,
        account_number=account.account_number,
        bank_name=account.bank_name,
        bank_code=account.bank_code,
        currency=account.currency,
        status=account.status,
        provider=account.provider,

        created_at=account.created_at,
        updated_at=account.updated_at,

        transactions=transaction_items,
    )


@router.patch(
    "/accounts/{account_id}/status",
    response_model=AdminMonnifyAccountListItem,
)
def update_monnify_account_status(
    account_id: UUID,
    payload: AdminMonnifyAccountStatusUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    account = db.scalar(
        select(MonnifyAccount).where(
            MonnifyAccount.id == account_id
        )
    )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monnify account not found",
        )

    user = db.scalar(
        select(User).where(User.id == account.user_id)
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account owner not found",
        )

    account.status = payload.status.strip()

    db.add(account)
    db.commit()
    db.refresh(account)

    return AdminMonnifyAccountListItem(
        id=account.id,
        user_id=account.user_id,
        wallet_id=account.wallet_id,
        user_email=user.email,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        account_reference=account.account_reference,
        reservation_reference=account.reservation_reference,
        account_name=account.account_name,
        account_number=account.account_number,
        bank_name=account.bank_name,
        bank_code=account.bank_code,
        currency=account.currency,
        status=account.status,
        provider=account.provider,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )