
import hashlib
import hmac
import json
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.database.database import SessionLocal, get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.monnify.client import MonnifyClient
from app.referral.service import maybe_reward_first_qualifying_credit


router = APIRouter(prefix="/monnify/deposit", tags=["Monnify Deposits"])

REFERENCE_PREFIX = "ONTIME-DEP-"
MIN_DEPOSIT = Decimal("100.00")
MAX_DEPOSIT = Decimal("1000000.00")


class DepositInitializeRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class DepositVerifyRequest(BaseModel):
    payment_reference: str = Field(min_length=20, max_length=100)


def _provider_body(response: dict) -> dict:
    if not response.get("requestSuccessful"):
        message = str(
            response.get("responseMessage")
            or response.get("message")
            or "Monnify rejected the payment request."
        )[:300]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Monnify rejected the payment request.",
                "provider_error": message,
            },
        )

    body = response.get("responseBody")
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from Monnify.",
        )
    return body


def _verify_provider_payment(payment_reference: str) -> dict:
    if not settings.MONNIFY_BASE_URL or not settings.MONNIFY_CONTRACT_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monnify payment configuration is incomplete.",
        )

    try:
        response = MonnifyClient().get(
            "/api/v2/merchant/transactions/query",
            params={"paymentReference": payment_reference},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to verify payment with Monnify.",
        ) from exc

    return _provider_body(response)


def _credit_verified_deposit(
    db: Session,
    *,
    payment_reference: str,
    provider_data: dict,
) -> dict:
    """Complete a pending deposit atomically and idempotently."""
    payment_status = str(
        provider_data.get("paymentStatus", "")
    ).upper()

    if payment_status not in {"PAID", "SUCCESSFUL"}:
        return {"status": "pending", "message": "Payment is not confirmed yet."}

    try:
        amount_paid = Decimal(
            str(provider_data.get("amountPaid", provider_data.get("amount")))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Monnify returned an invalid payment amount.",
        )

    currency = str(
        provider_data.get("currencyCode", provider_data.get("currency", ""))
    ).upper()

    if amount_paid <= 0 or currency != "NGN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment amount or currency.",
        )

    # Lock the pending transaction so concurrent verification/webhook
    # requests cannot credit the same deposit twice.
    transaction = db.scalar(
        select(Transaction)
        .where(Transaction.reference == payment_reference)
        .with_for_update()
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deposit reference not found.",
        )

    if transaction.provider != "monnify" or transaction.transaction_type != "deposit":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reference is not a Monnify deposit.",
        )

    if transaction.status == "completed":
        return {
            "status": "already_processed",
            "reference": transaction.reference,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
        }

    if transaction.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This deposit is not awaiting payment.",
        )

    if transaction.amount != amount_paid or transaction.currency.upper() != currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verified payment does not match the pending deposit.",
        )

    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.id == transaction.wallet_id)
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
    wallet.balance = balance_before + amount_paid

    transaction.balance_before = balance_before
    transaction.balance_after = wallet.balance
    transaction.status = "completed"
    transaction.provider_reference = str(
        provider_data.get("transactionReference")
        or provider_data.get("paymentReference")
        or payment_reference
    )

    maybe_reward_first_qualifying_credit(
        db,
        referred_user_id=wallet.user_id,
        credited_amount=amount_paid,
        transaction_type="deposit",
    )

    db.commit()
    db.refresh(transaction)

    return {
        "status": "completed",
        "reference": transaction.reference,
        "amount": str(amount_paid),
        "currency": currency,
        "wallet_balance": str(wallet.balance),
    }


@router.post("/initialize")
def initialize_deposit(
    payload: DepositInitializeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        amount = Decimal(str(payload.amount)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid deposit amount.",
        ) from exc

    if amount < MIN_DEPOSIT or amount > MAX_DEPOSIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deposit must be between NGN 100 and NGN 1,000,000.",
        )

    if not settings.MONNIFY_BASE_URL or not settings.MONNIFY_CONTRACT_CODE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monnify payment configuration is incomplete.",
        )

    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.user_id == current_user.id)
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

    reference = f"{REFERENCE_PREFIX}{uuid.uuid4().hex.upper()}"

    transaction = Transaction(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        reference=reference,
        transaction_type="deposit",
        direction="credit",
        amount=amount,
        balance_before=wallet.balance,
        balance_after=wallet.balance,
        currency="NGN",
        status="pending",
        provider="monnify",
        provider_reference=reference,
        description="ONTIME wallet funding",
    )

    db.add(transaction)
    db.commit()

    # Save the pending reference before contacting the payment provider.
    # If the network response is uncertain, the pending record can be
    # reconciled instead of creating another deposit reference.
    try:
        response = MonnifyClient().post(
            "/api/v1/merchant/transactions/init-transaction",
            data={
                "amount": float(amount),
                "customerName": " ".join(
                    part for part in [
                        current_user.first_name,
                        current_user.last_name,
                    ] if part
                ) or current_user.email,
                "customerEmail": current_user.email,
                "paymentReference": reference,
                "paymentDescription": "ONTIME SUBDATA LTD wallet funding",
                "currencyCode": "NGN",
                "contractCode": settings.MONNIFY_CONTRACT_CODE,
                "redirectUrl": (
                    f"{settings.FRONTEND_URL.rstrip('/')}"
                    f"/wallet/deposit/callback?reference={reference}"
                ),
                "paymentMethods": ["CARD", "ACCOUNT_TRANSFER"],
                "metadata": {
                    "walletId": str(wallet.id),
                    "userId": str(current_user.id),
                    "depositReference": reference,
                },
            },
        )
        body = _provider_body(response)
    except HTTPException:
        raise
    except RuntimeError as exc:
        # Keep the pending record because a timeout does not prove
        # that Monnify rejected the payment request.
        provider_message = str(exc)[:300]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Monnify checkout initialization failed.",
                "provider_error": provider_message,
                "action": (
                    "Check the Monnify configuration and reconcile "
                    "the pending reference before retrying."
                ),
            },
        ) from exc

    checkout_url = body.get("checkoutUrl")
    if not checkout_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Monnify did not return a checkout URL.",
        )

    return {
        "success": True,
        "message": "Checkout initialized. Complete payment to fund your wallet.",
        "data": {
            "reference": reference,
            "amount": str(amount),
            "currency": "NGN",
            "status": "pending",
            "checkout_url": checkout_url,
        },
    }


@router.post("/verify")
def verify_deposit(
    payload: DepositVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reference = payload.payment_reference.strip()

    if not reference.startswith(REFERENCE_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid deposit reference.",
        )

    transaction = db.scalar(
        select(Transaction)
        .join(Wallet, Wallet.id == Transaction.wallet_id)
        .where(
            Transaction.reference == reference,
            Wallet.user_id == current_user.id,
        )
    )

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deposit reference not found for this user.",
        )

    if transaction.status == "completed":
        return {
            "success": True,
            "data": {
                "reference": reference,
                "status": "completed",
                "amount": str(transaction.amount),
                "currency": transaction.currency,
            },
        }

    provider_data = _verify_provider_payment(reference)
    result = _credit_verified_deposit(
        db,
        payment_reference=reference,
        provider_data=provider_data,
    )

    return {"success": True, "data": result}


@router.post("/webhook")
async def deposit_webhook(
    request: Request,
    monnify_signature: str | None = Header(
        default=None, alias="monnify-signature"
    ),
):
    raw_body = await request.body()

    # Unlike the legacy reserved-account webhook, this hosted-checkout
    # webhook always requires a valid signature, including in sandbox.
    if not monnify_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Monnify webhook signature.",
        )

    expected = hmac.new(
        settings.MONNIFY_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    if not hmac.compare_digest(expected, monnify_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Monnify webhook signature.",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook JSON.",
        ) from exc

    if payload.get("eventType") != "SUCCESSFUL_TRANSACTION":
        return {"status": "ignored"}

    event_data = payload.get("eventData") or {}
    reference = str(event_data.get("paymentReference") or "")

    if not reference.startswith(REFERENCE_PREFIX):
        return {"status": "ignored", "message": "Not an ONTIME checkout deposit."}

    # Never credit from webhook contents alone. Query Monnify independently.
    provider_data = _verify_provider_payment(reference)
    db = SessionLocal()

    try:
        result = _credit_verified_deposit(
            db,
            payment_reference=reference,
            provider_data=provider_data,
        )
        return {"status": result["status"], "reference": reference}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
