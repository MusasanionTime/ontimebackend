from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.database.database import get_db
from app.models.admin import Admin
from app.models.crypto_exchange import CryptoExchange
from app.models.user import User
from app.schemas.admin_changenow import (
    AdminChangeNowExchangeDetailResponse,
    AdminChangeNowExchangeListItem,
    AdminChangeNowExchangeListResponse,
    AdminChangeNowExchangeStatusUpdate,
)


router = APIRouter(
    prefix="/admin/changenow",
    tags=["Admin ChangeNOW"],
)


@router.get(
    "/exchanges",
    response_model=AdminChangeNowExchangeListResponse,
)
def list_changenow_exchanges(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status_filter: str | None = Query(None),
    user_id: UUID | None = Query(None),
    provider: str | None = Query(None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    query = (
        select(CryptoExchange, User)
        .join(User, User.id == CryptoExchange.user_id)
    )

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            or_(
                CryptoExchange.provider_transaction_id.ilike(search_term),
                CryptoExchange.from_currency.ilike(search_term),
                CryptoExchange.to_currency.ilike(search_term),
                CryptoExchange.from_network.ilike(search_term),
                CryptoExchange.to_network.ilike(search_term),
                CryptoExchange.destination_address.ilike(search_term),
                CryptoExchange.refund_address.ilike(search_term),
                CryptoExchange.deposit_address.ilike(search_term),
                CryptoExchange.deposit_extra_id.ilike(search_term),
                CryptoExchange.rate_id.ilike(search_term),
                CryptoExchange.status.ilike(search_term),
                User.email.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term),
            )
        )

    if status_filter:
        query = query.where(
            CryptoExchange.status == status_filter
        )

    if user_id:
        query = query.where(
            CryptoExchange.user_id == user_id
        )

    if provider:
        query = query.where(
            CryptoExchange.provider == provider
        )

    count_query = select(func.count()).select_from(
        query.subquery()
    )

    total = db.scalar(count_query) or 0

    total_pages = ceil(total / page_size) if total else 0

    offset = (page - 1) * page_size

    rows = db.execute(
        query
        .order_by(CryptoExchange.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    items = [
        AdminChangeNowExchangeListItem(
            id=exchange.id,
            user_id=exchange.user_id,
            user_email=user.email,
            user_first_name=user.first_name,
            user_last_name=user.last_name,
            provider=exchange.provider,
            provider_transaction_id=exchange.provider_transaction_id,
            from_currency=exchange.from_currency,
            to_currency=exchange.to_currency,
            from_network=exchange.from_network,
            to_network=exchange.to_network,
            from_amount=exchange.from_amount,
            to_amount=exchange.to_amount,
            destination_address=exchange.destination_address,
            refund_address=exchange.refund_address,
            deposit_address=exchange.deposit_address,
            deposit_extra_id=exchange.deposit_extra_id,
            status=exchange.status,
            rate_id=exchange.rate_id,
            created_at=exchange.created_at,
            updated_at=exchange.updated_at,
        )
        for exchange, user in rows
    ]

    return AdminChangeNowExchangeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/exchanges/{exchange_id}",
    response_model=AdminChangeNowExchangeDetailResponse,
)
def get_changenow_exchange(
    exchange_id: UUID,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    exchange = db.scalar(
        select(CryptoExchange).where(
            CryptoExchange.id == exchange_id
        )
    )

    if not exchange:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ChangeNOW exchange not found",
        )

    user = db.scalar(
        select(User).where(
            User.id == exchange.user_id
        )
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exchange owner not found",
        )

    return AdminChangeNowExchangeDetailResponse(
        id=exchange.id,

        user_id=user.id,
        user_email=user.email,
        user_phone=user.phone,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        user_is_active=user.is_active,
        user_is_verified=user.is_verified,

        provider=exchange.provider,
        provider_transaction_id=exchange.provider_transaction_id,

        from_currency=exchange.from_currency,
        to_currency=exchange.to_currency,

        from_network=exchange.from_network,
        to_network=exchange.to_network,

        from_amount=exchange.from_amount,
        to_amount=exchange.to_amount,

        destination_address=exchange.destination_address,
        refund_address=exchange.refund_address,

        deposit_address=exchange.deposit_address,
        deposit_extra_id=exchange.deposit_extra_id,

        status=exchange.status,
        rate_id=exchange.rate_id,

        provider_response=exchange.provider_response,

        created_at=exchange.created_at,
        updated_at=exchange.updated_at,
    )


@router.patch(
    "/exchanges/{exchange_id}/status",
    response_model=AdminChangeNowExchangeListItem,
)
def update_changenow_exchange_status(
    exchange_id: UUID,
    payload: AdminChangeNowExchangeStatusUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    exchange = db.scalar(
        select(CryptoExchange).where(
            CryptoExchange.id == exchange_id
        )
    )

    if not exchange:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ChangeNOW exchange not found",
        )

    user = db.scalar(
        select(User).where(
            User.id == exchange.user_id
        )
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exchange owner not found",
        )

    new_status = payload.status.strip()

    if not new_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status cannot be empty",
        )

    exchange.status = new_status

    db.add(exchange)
    db.commit()
    db.refresh(exchange)

    return AdminChangeNowExchangeListItem(
        id=exchange.id,

        user_id=exchange.user_id,
        user_email=user.email,
        user_first_name=user.first_name,
        user_last_name=user.last_name,

        provider=exchange.provider,
        provider_transaction_id=exchange.provider_transaction_id,

        from_currency=exchange.from_currency,
        to_currency=exchange.to_currency,

        from_network=exchange.from_network,
        to_network=exchange.to_network,

        from_amount=exchange.from_amount,
        to_amount=exchange.to_amount,

        destination_address=exchange.destination_address,
        refund_address=exchange.refund_address,

        deposit_address=exchange.deposit_address,
        deposit_extra_id=exchange.deposit_extra_id,

        status=exchange.status,
        rate_id=exchange.rate_id,

        created_at=exchange.created_at,
        updated_at=exchange.updated_at,
    )