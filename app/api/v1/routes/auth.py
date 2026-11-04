import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.email_service import send_password_reset_email
from app.auth.dependencies import get_current_user
from app.auth.password_reset import (
    create_password_reset_token,
    reset_password,
)
from app.auth.security import hash_password, hash_transaction_pin
from app.database.database import get_db
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import RegisterRequest, RegisterResponse
from app.referral.service import create_referral_for_user, generate_referral_code
from app.wallet.number import generate_wallet_number
from app.schemas.password_reset import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.schemas.transaction_pin import (
    SetTransactionPinRequest,
    TransactionPinResponse,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# ============================================================
# REGISTER
# ============================================================


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    try:
        # 1. Check for an existing email
        existing_user = db.scalar(
            select(User).where(User.email == payload.email)
        )

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        # 2. Check for an existing phone number
        if payload.phone:
            existing_phone = db.scalar(
                select(User).where(User.phone == payload.phone)
            )

            if existing_phone:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This phone number is already registered.",
                )

        # 3. Validate an optional referral code
        referrer_code = (
            payload.referral_code.strip().upper()
            if payload.referral_code
            else None
        )

        referrer = None

        if referrer_code:
            referrer = db.scalar(
                select(User).where(
                    User.referral_code == referrer_code
                )
            )

            if not referrer:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid referral code.",
                )

            if not referrer.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This referral account is inactive.",
                )

        # 4. Create the new customer
        user = User(
            id=uuid.uuid4(),
            email=payload.email,
            phone=payload.phone,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            referral_code=generate_referral_code(db),
            referred_by_id=referrer.id if referrer else None,
            is_verified=False,
            is_active=True,
        )

        db.add(user)
        db.flush()

        # 5. Automatically create the customer's NGN wallet
        wallet = Wallet(
            id=uuid.uuid4(),
            user_id=user.id,
            wallet_number=generate_wallet_number(db),
            currency="NGN",
            balance=0,
            status="active",
        )

        db.add(wallet)
        db.flush()

        # 6. Record the referral relationship
        if referrer:
            create_referral_for_user(
                db,
                referrer_code=referrer.referral_code,
                referred_user_id=user.id,
            )

        # 7. Commit account, wallet and referral together
        db.commit()

        db.refresh(user)
        db.refresh(wallet)

        return RegisterResponse(
            id=str(user.id),
            email=user.email,
            wallet_currency=wallet.currency,
            wallet_number=wallet.wallet_number,
            referral_code=user.referral_code,
            account_number=None,
            bank_name=None,
            bank_code=None,
            message=(
                "ONTIME SUBDATA account and internal wallet "
                "created successfully."
            ),
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

# ============================================================
# GET CURRENT USER
# ============================================================


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wallet = db.scalar(
        select(Wallet).where(Wallet.user_id == current_user.id)
    )

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "phone": current_user.phone,
        "wallet_number": wallet.wallet_number if wallet else None,
        "referral_code": current_user.referral_code,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "is_verified": current_user.is_verified,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
        "has_transaction_pin": (
            current_user.transaction_pin_hash is not None
        ),
    }


# ============================================================
# SET TRANSACTION PIN
# ============================================================


@router.post(
    "/transaction-pin",
    response_model=TransactionPinResponse,
)
def set_transaction_pin(
    payload: SetTransactionPinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.transaction_pin_hash = hash_transaction_pin(
        payload.pin
    )

    db.add(current_user)
    db.commit()

    return TransactionPinResponse(
        message="Transaction PIN set successfully.",
        pin_set=True,
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.email == payload.email)
    )

    # Do not reveal whether the email exists.
    if not user or not user.is_active:
        return ForgotPasswordResponse(
            message=(
                "If an account exists with this email, "
                "a password reset link has been sent."
            )
        )

    reset_token, token = create_password_reset_token(
        db=db,
        user=user,
    )

    try:
        send_password_reset_email(
            recipient_email=str(user.email),
            reset_token=token,
        )

        db.commit()

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to send password reset email.",
        ) from exc

    return ForgotPasswordResponse(
        message=(
            "If an account exists with this email, "
            "a password reset link has been sent."
        )
    )


# ============================================================
# RESET PASSWORD
# ============================================================


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
)
def reset_user_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    try:
        reset_password(
            db=db,
            token=payload.token,
            new_password=payload.new_password,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ResetPasswordResponse(
        message="Password has been reset successfully."
    )