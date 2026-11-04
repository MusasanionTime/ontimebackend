from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.auth.security import create_access_token, verify_password
from app.database.database import get_db
from app.models.admin import Admin
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.admin import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminResponse,
)
from app.schemas.admin_transactions import (
    AdminTransactionDetailResponse,
    AdminTransactionListItem,
    AdminTransactionListResponse,
)
from app.schemas.admin_dashboard import AdminDashboardOverview
from app.schemas.admin_user_detail import (
    AdminUserDetailResponse,
    AdminUserTransaction,
    AdminUserWallet,
)
from app.schemas.admin_users import (
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserStatusUpdate,
)
from app.schemas.admin_wallet_detail import (
    AdminWalletDetailResponse,
    AdminWalletTransaction,
)
from app.schemas.admin_wallets import (
    AdminWalletListItem,
    AdminWalletListResponse,
    AdminWalletStatusUpdate,
    AdminWalletAdjustment,
)
from app.services.admin_dashboard import get_dashboard_overview
from app.services.admin_audit import create_admin_audit_log
from app.wallet.service import WalletService


router = APIRouter(
    prefix="/admin",
    tags=["Admin Authentication"],
)


# ============================================================
# ADMIN LOGIN
# ============================================================


@router.post(
    "/login",
    response_model=AdminLoginResponse,
)
def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = db.scalar(
        select(Admin).where(
            Admin.email == str(payload.email).lower()
        )
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive",
        )

    if not verify_password(
        payload.password,
        admin.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    admin.last_login_at = datetime.now(timezone.utc)

    create_admin_audit_log(
        db=db,
        admin=admin,
        action="ADMIN_LOGIN",
        resource_type="admin",
        resource_id=str(admin.id),
        description="Admin successfully logged in",
        request=request,
        extra_data={
            "email": admin.email,
        },
    )

    db.commit()
    db.refresh(admin)

    access_token = create_access_token(
        str(admin.id)
    )

    return AdminLoginResponse(
        access_token=access_token,
        admin=admin,
    )


# ============================================================
# CURRENT ADMIN
# ============================================================


@router.get(
    "/me",
    response_model=AdminResponse,
)
def admin_me(
    admin: Admin = Depends(get_current_admin),
):
    return admin


# ============================================================
# DASHBOARD OVERVIEW
# ============================================================


@router.get(
    "/dashboard/overview",
    response_model=AdminDashboardOverview,
)
def admin_dashboard_overview(
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return get_dashboard_overview(db)


# ============================================================
# LIST / SEARCH USERS
# ============================================================


@router.get(
    "/users",
    response_model=AdminUserListResponse,
)
def admin_list_users(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page must be greater than or equal to 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page size must be between 1 and 100",
        )

    query = select(User)

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            (User.email.ilike(search_term))
            | (User.phone.ilike(search_term))
            | (User.first_name.ilike(search_term))
            | (User.last_name.ilike(search_term))
        )

    total = len(
        db.scalars(query).all()
    )

    offset = (page - 1) * page_size

    users = db.scalars(
        query
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    total_pages = (
        (total + page_size - 1) // page_size
        if total > 0
        else 0
    )

    return AdminUserListResponse(
        items=[
            AdminUserListItem.model_validate(user)
            for user in users
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ============================================================
# GET USER DETAILS
# ============================================================


@router.get(
    "/users/{user_id}",
    response_model=AdminUserDetailResponse,
)
def admin_get_user(
    user_id: str,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    wallet = db.scalar(
        select(Wallet).where(
            Wallet.user_id == user.id
        )
    )

    transactions = []

    if wallet:
        transactions = db.scalars(
            select(Transaction)
            .where(
                Transaction.wallet_id == wallet.id
            )
            .order_by(
                Transaction.created_at.desc()
            )
            .limit(50)
        ).all()

    return AdminUserDetailResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        wallet=(
            AdminUserWallet.model_validate(wallet)
            if wallet
            else None
        ),
        transactions=[
            AdminUserTransaction.model_validate(transaction)
            for transaction in transactions
        ],
    )


# ============================================================
# ACTIVATE / DEACTIVATE USER
# ============================================================


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserListItem,
)
def admin_update_user_status(
    user_id: str,
    payload: AdminUserStatusUpdate,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    old_status = user.is_active
    new_status = payload.is_active

    user.is_active = new_status

    create_admin_audit_log(
        db=db,
        admin=admin,
        action="UPDATE_USER_STATUS",
        resource_type="user",
        resource_id=str(user.id),
        description=(
            f"Admin changed user status from "
            f"{'active' if old_status else 'inactive'} to "
            f"{'active' if new_status else 'inactive'}"
        ),
        request=request,
        extra_data={
            "old_is_active": old_status,
            "new_is_active": new_status,
            "user_email": user.email,
        },
    )

    db.commit()
    db.refresh(user)

    return user


# ============================================================
# LIST / SEARCH WALLETS
# ============================================================


@router.get(
    "/wallets",
    response_model=AdminWalletListResponse,
)
def admin_list_wallets(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status_filter: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page must be greater than or equal to 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page size must be between 1 and 100",
        )

    query = (
        select(Wallet, User)
        .join(User, Wallet.user_id == User.id)
    )

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            (User.email.ilike(search_term))
            | (User.phone.ilike(search_term))
            | (User.first_name.ilike(search_term))
            | (User.last_name.ilike(search_term))
        )

    if status_filter:
        query = query.where(
            Wallet.status == status_filter
        )

    rows = db.execute(query).all()

    total = len(rows)

    offset = (page - 1) * page_size

    paginated_rows = rows[
        offset:offset + page_size
    ]

    total_pages = (
        (total + page_size - 1) // page_size
        if total > 0
        else 0
    )

    items = [
        AdminWalletListItem(
            id=wallet.id,
            user_id=user.id,
            user_email=user.email,
            user_first_name=user.first_name,
            user_last_name=user.last_name,
            wallet_number=wallet.wallet_number,
            currency=wallet.currency,
            balance=wallet.balance,
            status=wallet.status,
            created_at=wallet.created_at,
            updated_at=wallet.updated_at,
        )
        for wallet, user in paginated_rows
    ]

    return AdminWalletListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ============================================================
# GET WALLET DETAILS
# ============================================================


@router.get(
    "/wallets/{wallet_id}",
    response_model=AdminWalletDetailResponse,
)
def admin_get_wallet(
    wallet_id: str,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    result = db.execute(
        select(Wallet, User)
        .join(User, Wallet.user_id == User.id)
        .where(Wallet.id == wallet_id)
    ).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    wallet, user = result

    transactions = db.scalars(
        select(Transaction)
        .where(
            Transaction.wallet_id == wallet.id
        )
        .order_by(
            Transaction.created_at.desc()
        )
        .limit(50)
    ).all()

    return AdminWalletDetailResponse(
        id=wallet.id,
        user_id=user.id,
        user_email=user.email,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        wallet_number=wallet.wallet_number,
        currency=wallet.currency,
        balance=wallet.balance,
        status=wallet.status,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
        transactions=[
            AdminWalletTransaction.model_validate(transaction)
            for transaction in transactions
        ],
    )


# ============================================================
# ACTIVATE / DEACTIVATE WALLET
# ============================================================


@router.patch(
    "/wallets/{wallet_id}/status",
    response_model=AdminWalletListItem,
)
def admin_update_wallet_status(
    wallet_id: str,
    payload: AdminWalletStatusUpdate,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    wallet = db.scalar(
        select(Wallet).where(
            Wallet.id == wallet_id
        )
    )

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )

    allowed_statuses = {
        "active",
        "inactive",
    }

    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet status must be either 'active' or 'inactive'",
        )

    old_status = wallet.status
    new_status = payload.status

    wallet.status = new_status

    user = db.scalar(
        select(User).where(
            User.id == wallet.user_id
        )
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet owner not found",
        )

    create_admin_audit_log(
        db=db,
        admin=admin,
        action="UPDATE_WALLET_STATUS",
        resource_type="wallet",
        resource_id=str(wallet.id),
        description=(
            f"Admin changed wallet status from "
            f"{old_status} to {new_status}"
        ),
        request=request,
        extra_data={
            "old_status": old_status,
            "new_status": new_status,
            "wallet_id": str(wallet.id),
            "user_id": str(user.id),
            "user_email": user.email,
        },
    )

    db.commit()
    db.refresh(wallet)

    return AdminWalletListItem(
        id=wallet.id,
        user_id=user.id,
        user_email=user.email,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        wallet_number=wallet.wallet_number,
        currency=wallet.currency,
        balance=wallet.balance,
        status=wallet.status,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
    )


# ============================================================
# CUSTOMER WALLET BALANCE MANAGEMENT
# ============================================================


@router.post(
    "/wallets/{wallet_id}/credit",
    response_model=AdminWalletTransaction,
    status_code=status.HTTP_201_CREATED,
)
def admin_credit_wallet(
    wallet_id: str,
    payload: AdminWalletAdjustment,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        transaction = WalletService.credit(
            db,
            wallet_id=wallet_id,
            amount=payload.amount,
            reference=payload.reference,
            transaction_type=payload.transaction_type,
            description=payload.description or "Admin wallet credit.",
        )
        create_admin_audit_log(
            db, admin, "ADMIN_WALLET_CREDIT", "wallet", str(wallet_id),
            "Admin credited customer wallet", request,
            {"amount": str(payload.amount), "reference": payload.reference},
        )
        db.commit()
        db.refresh(transaction)
        return transaction
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to credit wallet.") from exc


@router.post(
    "/wallets/{wallet_id}/debit",
    response_model=AdminWalletTransaction,
    status_code=status.HTTP_201_CREATED,
)
def admin_debit_wallet(
    wallet_id: str,
    payload: AdminWalletAdjustment,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        transaction = WalletService.debit(
            db,
            wallet_id=wallet_id,
            amount=payload.amount,
            reference=payload.reference,
            transaction_type=payload.transaction_type,
            description=payload.description or "Admin wallet debit.",
        )
        create_admin_audit_log(
            db, admin, "ADMIN_WALLET_DEBIT", "wallet", str(wallet_id),
            "Admin debited customer wallet", request,
            {"amount": str(payload.amount), "reference": payload.reference},
        )
        db.commit()
        db.refresh(transaction)
        return transaction
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to debit wallet.") from exc


# ============================================================
# LIST / SEARCH / FILTER TRANSACTIONS
# ============================================================


@router.get(
    "/transactions",
    response_model=AdminTransactionListResponse,
)
def admin_list_transactions(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status_filter: str | None = None,
    transaction_type: str | None = None,
    direction: str | None = None,
    provider: str | None = None,
    wallet_id: str | None = None,
    user_id: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page must be greater than or equal to 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page size must be between 1 and 100",
        )

    query = (
        select(Transaction, Wallet, User)
        .join(
            Wallet,
            Transaction.wallet_id == Wallet.id,
        )
        .join(
            User,
            Wallet.user_id == User.id,
        )
    )

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            (Transaction.reference.ilike(search_term))
            | (
                Transaction.provider_reference.ilike(
                    search_term
                )
            )
            | (
                Transaction.description.ilike(
                    search_term
                )
            )
            | (User.email.ilike(search_term))
            | (User.phone.ilike(search_term))
            | (User.first_name.ilike(search_term))
            | (User.last_name.ilike(search_term))
        )

    # --------------------------------------------------------
    # FILTER BY STATUS
    # --------------------------------------------------------

    if status_filter:
        query = query.where(
            Transaction.status == status_filter
        )

    # --------------------------------------------------------
    # FILTER BY TRANSACTION TYPE
    # --------------------------------------------------------

    if transaction_type:
        query = query.where(
            Transaction.transaction_type
            == transaction_type
        )

    # --------------------------------------------------------
    # FILTER BY DIRECTION
    # --------------------------------------------------------

    if direction:
        query = query.where(
            Transaction.direction == direction
        )

    # --------------------------------------------------------
    # FILTER BY PROVIDER
    # --------------------------------------------------------

    if provider:
        query = query.where(
            Transaction.provider == provider
        )

    # --------------------------------------------------------
    # FILTER BY WALLET
    # --------------------------------------------------------

    if wallet_id:
        query = query.where(
            Transaction.wallet_id == wallet_id
        )

    # --------------------------------------------------------
    # FILTER BY USER
    # --------------------------------------------------------

    if user_id:
        query = query.where(
            Wallet.user_id == user_id
        )

    # --------------------------------------------------------
    # GET RESULTS
    # --------------------------------------------------------

    rows = db.execute(
        query
        .order_by(
            Transaction.created_at.desc()
        )
    ).all()

    total = len(rows)

    offset = (page - 1) * page_size

    paginated_rows = rows[
        offset:offset + page_size
    ]

    total_pages = (
        (total + page_size - 1) // page_size
        if total > 0
        else 0
    )

    # --------------------------------------------------------
    # BUILD RESPONSE
    # --------------------------------------------------------

    items = [
        AdminTransactionListItem(
            id=transaction.id,
            wallet_id=wallet.id,
            user_id=user.id,
            user_email=user.email,
            user_first_name=user.first_name,
            user_last_name=user.last_name,
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
        for transaction, wallet, user in paginated_rows
    ]

    return AdminTransactionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ============================================================
# GET TRANSACTION DETAILS
# ============================================================


@router.get(
    "/transactions/{transaction_id}",
    response_model=AdminTransactionDetailResponse,
)
def admin_get_transaction(
    transaction_id: str,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    result = db.execute(
        select(Transaction, Wallet, User)
        .join(
            Wallet,
            Transaction.wallet_id == Wallet.id,
        )
        .join(
            User,
            Wallet.user_id == User.id,
        )
        .where(
            Transaction.id == transaction_id
        )
    ).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    transaction, wallet, user = result

    return AdminTransactionDetailResponse(
        id=transaction.id,
        wallet_id=wallet.id,
        wallet_currency=wallet.currency,
        wallet_balance=wallet.balance,
        wallet_status=wallet.status,
        user_id=user.id,
        user_email=user.email,
        user_phone=user.phone,
        user_first_name=user.first_name,
        user_last_name=user.last_name,
        user_is_active=user.is_active,
        user_is_verified=user.is_verified,
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