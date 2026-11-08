import hashlib
import hmac
import json
import logging
import uuid

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.database.database import SessionLocal, get_db
from app.models.admin import Admin
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.monnify.client import MonnifyClient
from app.referral.service import maybe_reward_first_qualifying_credit


logger = logging.getLogger("ontime.payments.monnify")

router = APIRouter(tags=["Wallet Deposits"])

REFERENCE_PREFIX = "ONTIME-DEP-"

MIN_DEPOSIT = Decimal("100.00")
MAX_DEPOSIT = Decimal("1000000.00")

INVOICE_TTL_MINUTES = 30

CURRENCY = "NGN"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class DepositInitializeRequest(BaseModel):
    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
    )


class DepositVerifyRequest(BaseModel):
    payment_reference: str = Field(
        min_length=20,
        max_length=100,
    )


# ============================================================
# HELPERS
# ============================================================

def money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Invalid monetary value returned by payment provider.",
        ) from exc


def provider_body(response: dict) -> dict:
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=502,
            detail="Invalid Monnify response.",
        )

    body = response.get("responseBody")

    if (
        not response.get("requestSuccessful")
        or not isinstance(body, dict)
    ):
        raise HTTPException(
            status_code=502,
            detail="Monnify did not accept the request.",
        )

    return body


def log_provider_error(
    operation: str,
    reference: str,
    exc: Exception,
):
    logger.error(
        "Monnify operation failed: operation=%s reference=%s "
        "error_type=%s",
        operation,
        reference,
        type(exc).__name__,
        exc_info=True,
    )


def verify_provider_payment(
    payment_reference: str,
) -> dict:
    """
    Verify payment directly with Monnify.

    payment_reference is the merchant-generated reference
    supplied when creating the invoice.
    """

    try:
        response = MonnifyClient().get(
            "/api/v2/merchant/transactions/query",
            params={
                "paymentReference": payment_reference,
            },
        )

        return provider_body(response)

    except HTTPException:
        raise

    except Exception as exc:
        log_provider_error(
            "transaction_verification",
            payment_reference,
            exc,
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to verify payment with Monnify. Try again later.",
        ) from exc


def valid_webhook_signature(
    raw_body: bytes,
    signature: str,
    secret: str,
) -> bool:

    if not signature or not secret:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(
        expected.lower(),
        signature.strip().lower(),
    )


# ============================================================
# DEPOSIT RESPONSE
# ============================================================

def deposit_view(transaction: Transaction) -> dict:

    metadata = transaction.provider_metadata or {}

    return {
        "reference": transaction.reference,
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "status": transaction.status,
        "provider": transaction.provider,
        "provider_reference": transaction.provider_reference,
        "description": transaction.description,
        "created_at": transaction.created_at,

        "bank_transfer": metadata.get("bank_transfer"),
        "checkout_url": metadata.get("checkout_url"),
        "expires_at": metadata.get("expires_at"),

        "customer_pays_fees": metadata.get(
            "customer_pays_fees"
        ),

        "invoice_status": metadata.get("invoice_status"),

        "fee_note": (
            "Applicable fees are determined by Monnify "
            "according to the merchant contract and payment method."
        ),
    }


# ============================================================
# CREDIT VERIFIED DEPOSIT
# ============================================================

def credit_verified_deposit(
    db: Session,
    *,
    payment_reference: str,
    provider_data: dict,
) -> dict:

    if not isinstance(provider_data, dict):
        raise HTTPException(
            status_code=502,
            detail="Invalid payment verification response.",
        )

    payment_status = str(
        provider_data.get("paymentStatus", "")
    ).upper()

    if payment_status != "PAID":
        return {
            "status": payment_status.lower() or "pending",
            "reference": payment_reference,
        }

    try:
        amount_paid = money(
            provider_data.get("amountPaid")
        )

        total_payable = money(
            provider_data.get(
                "totalPayable",
                provider_data.get("amountPaid"),
            )
        )

        invoice_amount_value = provider_data.get("amount")

        invoice_amount = (
            money(invoice_amount_value)
            if invoice_amount_value is not None
            else None
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Invalid payment amount from Monnify.",
        ) from exc

    currency = str(
        provider_data.get(
            "currencyCode",
            provider_data.get("currency", ""),
        )
    ).upper()

    verified_reference = str(
        provider_data.get("paymentReference", "")
    )

    if verified_reference != payment_reference:
        raise HTTPException(
            status_code=400,
            detail="Monnify payment reference does not match.",
        )

    # Lock the deposit row to prevent concurrent wallet credits.
    transaction = db.scalar(
        select(Transaction)
        .where(
            Transaction.reference == payment_reference,
            Transaction.provider == "monnify",
            Transaction.transaction_type == "deposit",
        )
        .with_for_update()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Deposit reference not found.",
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
            status_code=409,
            detail="Deposit is not awaiting payment.",
        )

    expected_amount = money(transaction.amount)

    if (
        invoice_amount is not None
        and invoice_amount != expected_amount
    ):
        raise HTTPException(
            status_code=400,
            detail="Invoice amount does not match the deposit.",
        )

    if (
        amount_paid != total_payable
        or amount_paid < expected_amount
        or currency != transaction.currency.upper()
    ):
        raise HTTPException(
            status_code=400,
            detail="Payment amount or currency does not match the deposit.",
        )

    # Lock wallet before modifying its balance.
    wallet = db.scalar(
        select(Wallet)
        .where(
            Wallet.id == transaction.wallet_id
        )
        .with_for_update()
    )

    if not wallet or wallet.status.lower() != "active":
        raise HTTPException(
            status_code=409,
            detail="Customer wallet is unavailable.",
        )

    before = money(wallet.balance)

    new_balance = before + expected_amount

    wallet.balance = new_balance

    transaction.balance_before = before
    transaction.balance_after = new_balance

    transaction.status = "completed"

    transaction.provider_reference = str(
        provider_data.get("transactionReference")
        or verified_reference
    )

    transaction.provider_metadata = {
        **(transaction.provider_metadata or {}),

        "invoice_status": "PAID",

        "amount_paid": str(amount_paid),
        "total_payable": str(total_payable),

        "provider_transaction_reference": str(
            provider_data.get("transactionReference", "")
        ),

        "customer_pays_fees": (
            total_payable > expected_amount
        ),

        "paid_at": str(
            provider_data.get("paidOn", "")
        ),
    }

    # Referral reward runs inside the same database transaction.
    # Any failure must roll back the wallet credit as well.
    maybe_reward_first_qualifying_credit(
        db,
        referred_user_id=wallet.user_id,
        credited_amount=expected_amount,
        transaction_type="deposit",
    )

    db.commit()

    logger.info(
        "ONTIME deposit credited successfully: reference=%s amount=%s",
        transaction.reference,
        expected_amount,
    )

    return {
        "status": "completed",
        "reference": transaction.reference,
        "amount": str(expected_amount),
        "amount_paid": str(amount_paid),
        "total_payable": str(total_payable),
        "currency": currency,
        "wallet_balance": str(new_balance),
    }


# ============================================================
# INITIALIZE DEPOSIT
# ============================================================

@router.post("/wallet/deposits/initialize")
@router.post(
    "/monnify/deposit/initialize",
    include_in_schema=False,
)
def initialize_deposit(
    payload: DepositInitializeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    amount = money(payload.amount)

    if not MIN_DEPOSIT <= amount <= MAX_DEPOSIT:
        raise HTTPException(
            status_code=400,
            detail="Deposit must be between NGN 100 and NGN 1,000,000.",
        )

    if (
        not settings.MONNIFY_CONTRACT_CODE
        or not settings.MONNIFY_API_KEY
        or not settings.MONNIFY_SECRET_KEY
    ):
        raise HTTPException(
            status_code=503,
            detail="Monnify payment configuration is incomplete.",
        )

    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.user_id == current_user.id)
        .with_for_update()
    )

    if not wallet or wallet.status.lower() != "active":
        raise HTTPException(
            status_code=409,
            detail="An active wallet is required to fund your account.",
        )

    reference = (
        f"{REFERENCE_PREFIX}{uuid.uuid4().hex.upper()}"
    )

    now = datetime.now(timezone.utc)

    expires = now + timedelta(
        minutes=INVOICE_TTL_MINUTES
    )

    transaction = Transaction(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        reference=reference,
        transaction_type="deposit",
        direction="credit",
        amount=amount,
        balance_before=wallet.balance,
        balance_after=wallet.balance,
        currency=CURRENCY,
        status="pending",
        provider="monnify",
        provider_reference=reference,
        description="ONTIME wallet funding",
        provider_metadata={
            "invoice_status": "initializing",
            "customer_pays_fees": True,
        },
    )

    db.add(transaction)

    try:
        # Save the local reference BEFORE contacting Monnify.
        db.commit()
        db.refresh(transaction)

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Could not save ONTIME deposit reference."
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to create deposit record.",
        ) from exc

    customer_name = " ".join(
        part
        for part in [
            current_user.first_name,
            current_user.last_name,
        ]
        if part
    ) or current_user.email

    invoice_payload = {
        "invoiceReference": reference,
        "amount": float(amount),
        "invoiceDescription": "ONTIME SUBDATA LTD wallet funding",
        "currencyCode": CURRENCY,
        "contractCode": settings.MONNIFY_CONTRACT_CODE,
        "customerEmail": current_user.email,
        "customerName": customer_name,
        # Convert the UTC expiry instant to Nigeria time
        # before formatting the timezone-free Monnify date string.
        "expiryDate": expires.astimezone(
            ZoneInfo("Africa/Lagos")
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "redirectUrl": (
            f"{settings.FRONTEND_URL.rstrip('/')}"
            f"/wallet/deposit/callback?reference={reference}"
        ),
    }

    try:
        response = MonnifyClient().post(
            "/api/v1/invoice/create",
            data=invoice_payload,
        )

        body = provider_body(response)

        returned_reference = str(
            body.get("invoiceReference", "")
        )

        if returned_reference != reference:
            raise RuntimeError(
                "Monnify returned a mismatched invoice reference."
            )

    except Exception as exc:
        log_provider_error(
            "invoice_initialization",
            reference,
            exc,
        )

        # Do NOT delete the local record or create another invoice.
        # The provider may have received the original request.
        try:
            transaction.provider_metadata = {
                **(transaction.provider_metadata or {}),
                "invoice_status": "initialization_unknown",
                "initialization_error_type": type(exc).__name__,
                "reconciliation_required": True,
            }

            db.commit()

        except Exception:
            db.rollback()

            logger.exception(
                "Unable to save invoice failure state: reference=%s",
                reference,
            )

        raise HTTPException(
            status_code=502,
            detail=(
                "Monnify invoice initialization could not be confirmed. "
                "The deposit reference has been retained for reconciliation. "
                "Do not create another deposit yet."
            ),
        ) from exc

    bank_transfer = {
        key: body.get(key)
        for key in (
            "accountNumber",
            "accountName",
            "bankName",
            "bankCode",
        )
        if body.get(key)
    }

    transaction.provider_metadata = {
        **(transaction.provider_metadata or {}),

        "invoice_status": body.get("invoiceStatus"),
        "invoice_amount": str(
            body.get("amount", amount)
        ),

        "expires_at": body.get("expiryDate"),
        "bank_transfer": bank_transfer or None,
        "checkout_url": body.get("checkoutUrl"),

        "customer_pays_fees": None,

        "fee_note": (
            "Applicable fees are determined by the Monnify merchant "
            "contract and selected payment method."
        ),
    }

    try:
        db.commit()
        db.refresh(transaction)

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Invoice created but local response could not be saved: reference=%s",
            reference,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Monnify may have created the invoice, but ONTIME "
                "could not save its details. Reconcile this reference."
            ),
        ) from exc

    return {
        "success": True,
        "data": deposit_view(transaction),
    }


# ============================================================
# CUSTOMER DEPOSIT HISTORY
# ============================================================

@router.get("/wallet/deposits")
def list_deposits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
            status_code=404,
            detail="Wallet not found.",
        )

    rows = db.scalars(
        select(Transaction)
        .where(
            Transaction.wallet_id == wallet.id,
            Transaction.transaction_type == "deposit",
        )
        .order_by(Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": [
            deposit_view(row)
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# GET ONE DEPOSIT
# ============================================================

@router.get("/wallet/deposits/{reference}")
@router.get(
    "/monnify/deposit/{reference}",
    include_in_schema=False,
)
def get_deposit(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    row = db.scalar(
        select(Transaction)
        .join(
            Wallet,
            Wallet.id == Transaction.wallet_id,
        )
        .where(
            Transaction.reference == reference,
            Wallet.user_id == current_user.id,
            Transaction.transaction_type == "deposit",
        )
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Deposit not found.",
        )

    return {
        "success": True,
        "data": deposit_view(row),
    }


# ============================================================
# VERIFY DEPOSIT
# ============================================================

@router.post("/wallet/deposits/{reference}/verify")
def verify_deposit(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    row = db.scalar(
        select(Transaction)
        .join(
            Wallet,
            Wallet.id == Transaction.wallet_id,
        )
        .where(
            Transaction.reference == reference,
            Wallet.user_id == current_user.id,
            Transaction.transaction_type == "deposit",
        )
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Deposit not found.",
        )

    if row.status == "completed":
        return {
            "success": True,
            "data": deposit_view(row),
        }

    provider_data = verify_provider_payment(reference)

    result = credit_verified_deposit(
        db,
        payment_reference=reference,
        provider_data=provider_data,
    )

    return {
        "success": True,
        "data": result,
    }


# ============================================================
# MONNIFY WEBHOOK
# ============================================================

@router.post("/payments/webhooks/monnify")
@router.post(
    "/monnify/deposit/webhook",
    include_in_schema=False,
)
async def deposit_webhook(
    request: Request,
    monnify_signature: str | None = Header(
        default=None,
        alias="monnify-signature",
    ),
):

    raw_body = await request.body()

    secret = settings.MONNIFY_SECRET_KEY or ""

    sandbox = (
        "sandbox" in (
            settings.MONNIFY_BASE_URL or ""
        ).lower()
    )

    # Monnify sandbox notifications may not include signatures.
    if not monnify_signature:
        if not (settings.DEBUG and sandbox):
            raise HTTPException(
                status_code=401,
                detail="Missing Monnify webhook signature.",
            )

    elif not valid_webhook_signature(
        raw_body,
        monnify_signature,
        secret,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Monnify webhook signature.",
        )

    try:
        event = json.loads(raw_body)

    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON.",
        ) from exc

    if not isinstance(event, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload.",
        )

    event_type = event.get("eventType")

    if event_type != "SUCCESSFUL_TRANSACTION":
        return {
            "status": "ignored",
        }

    event_data = event.get("eventData") or {}

    if not isinstance(event_data, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook event data.",
        )

    payment_reference = str(
        event_data.get("paymentReference") or ""
    )

    if not payment_reference.startswith(
        REFERENCE_PREFIX
    ):
        return {
            "status": "ignored",
        }

    # Always verify directly with Monnify.
    provider_data = verify_provider_payment(
        payment_reference
    )

    db = SessionLocal()

    try:
        result = credit_verified_deposit(
            db,
            payment_reference=payment_reference,
            provider_data=provider_data,
        )

        return result

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


# ============================================================
# ADMIN DEPOSIT MONITORING
# ============================================================

@router.get("/admin/deposits")
def admin_list_deposits(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(
        None,
        alias="status",
    ),
    reference: str | None = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):

    query = select(Transaction).where(
        Transaction.provider == "monnify",
        Transaction.transaction_type == "deposit",
    )

    if status_filter:
        query = query.where(
            Transaction.status == status_filter
        )

    if reference:
        query = query.where(
            Transaction.reference == reference
        )

    rows = db.scalars(
        query
        .order_by(Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": [
            {
                **deposit_view(row),
                "wallet_id": str(row.wallet_id),
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# ADMIN RECONCILIATION
# ============================================================

@router.post("/admin/deposits/{reference}/reconcile")
def admin_reconcile_deposit(
    reference: str,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):

    row = db.scalar(
        select(Transaction)
        .where(
            Transaction.reference == reference,
            Transaction.provider == "monnify",
            Transaction.transaction_type == "deposit",
        )
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Deposit not found.",
        )

    if row.status == "completed":
        return {
            "success": True,
            "data": {
                "status": "already_processed",
                "reference": reference,
            },
        }

    provider_data = verify_provider_payment(reference)

    result = credit_verified_deposit(
        db,
        payment_reference=reference,
        provider_data=provider_data,
    )

    logger.info(
        "Admin deposit reconciliation: reference=%s admin_id=%s result=%s",
        reference,
        str(admin.id),
        result.get("status"),
    )

    return {
        "success": True,
        "data": result,
    }