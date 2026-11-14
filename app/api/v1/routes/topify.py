import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.admin import get_current_admin
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.database.database import SessionLocal, get_db
from app.models.topify_account import TopifyAccount
from app.models.topify_webhook_event import TopifyWebhookEvent
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.topify.client import TopifyClient
from app.topify.service import (
    kobo_to_naira,
    parse_kobo,
    safe_event_metadata,
    topify_transaction_key,
    verify_webhook_signature,
)
from app.wallet.service import WalletService

logger = logging.getLogger("ontime.payments.topify")

router = APIRouter(prefix="/topify", tags=["Topify"])

SUPPORTED_EVENTS = {
    "customer.virtual_account.created",
    "charge.success",
    "wallet.funded",
    "charge.failed",
    "transaction.reversed",
}


def _require_enabled(*, reservation: bool = False) -> None:
    if not settings.TOPIFY_ENABLED:
        raise HTTPException(status_code=503, detail="Topify is not enabled.")
    if not settings.TOPIFY_API_KEY:
        raise HTTPException(
            status_code=503, detail="Topify API credentials are not configured."
        )
    if reservation and not settings.TOPIFY_BUSINESS_ID:
        raise HTTPException(
            status_code=503, detail="Topify business approval is not configured."
        )


def _account_view(account: TopifyAccount) -> dict:
    return {
        "provider": "topify",
        "bank_provider": "moniepoint",
        "bank_code": account.bank_code,
        "customer_code": account.customer_code,
        "account_number": account.account_number,
        "account_name": account.account_name,
        "bank_name": account.bank_name,
        "currency": account.currency,
        "status": account.status,
        "is_sandbox": account.is_sandbox,
    }


def _name_for_user(user: User) -> str:
    first_name = (user.first_name or "").strip()
    last_name = (user.last_name or "").strip()
    if not first_name or not last_name:
        raise HTTPException(
            status_code=400,
            detail="Add your first and last name before reserving an account.",
        )
    name = f"{first_name} {last_name}"
    return name[:200]


@router.post("/accounts/reserve")
def reserve_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_enabled()
    phone = (current_user.phone or "").strip()
    if not phone:
        raise HTTPException(
            status_code=400,
            detail="Add a phone number before reserving a Topify account.",
        )
    if not current_user.email:
        raise HTTPException(
            status_code=400,
            detail="A customer email is required for Topify account reservation.",
        )

    wallet = db.scalar(
        select(Wallet).where(Wallet.user_id == current_user.id).with_for_update()
    )
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    if wallet.status.lower() != "active" or wallet.currency.upper() != "NGN":
        raise HTTPException(
            status_code=409, detail="An active NGN wallet is required for Topify."
        )

    account = db.scalar(
        select(TopifyAccount)
        .where(TopifyAccount.user_id == current_user.id)
        .with_for_update()
    )
    if account and account.status == "active" and account.account_number:
        return {"success": True, "data": _account_view(account)}

    _require_enabled(reservation=True)

    if not account:
        account = TopifyAccount(
            id=uuid.uuid4(),
            user_id=current_user.id,
            wallet_id=wallet.id,
            request_email=current_user.email,
            request_name=_name_for_user(current_user),
            request_phone=phone,
            bank_code="30901",
            currency="NGN",
            status="pending",
        )
        db.add(account)
        try:
            db.commit()
            db.refresh(account)
        except IntegrityError as exc:
            db.rollback()
            account = db.scalar(
                select(TopifyAccount).where(TopifyAccount.user_id == current_user.id)
            )
            if not account:
                raise HTTPException(
                    status_code=409,
                    detail="A Topify account request is already being processed.",
                ) from exc
    account.status = "pending"
    db.commit()

    try:
        result = TopifyClient().reserve_virtual_account(
            email=account.request_email,
            name=account.request_name,
            phone_number=account.request_phone,
            business_id=settings.TOPIFY_BUSINESS_ID,
        )
    except RuntimeError as exc:
        # Keep the row pending. Topify documents the reservation tuple as idempotent,
        # so an uncertain request can be retried with exactly the same values.
        raise HTTPException(
            status_code=502,
            detail="Topify could not confirm the account request. It remains pending; retry later.",
        ) from exc

    customer = (
        result.get("customer") if isinstance(result.get("customer"), dict) else {}
    )
    accounts = result.get("accounts")
    moniepoint = next(
        (
            item
            for item in accounts or []
            if isinstance(item, dict)
            and str(item.get("provider", "")).lower() in {"moniepoint", "30901"}
        ),
        None,
    )
    if (
        not moniepoint
        or not moniepoint.get("account_number")
        or not customer.get("customer_code")
    ):
        raise HTTPException(
            status_code=502,
            detail="Topify accepted the request but returned no complete Moniepoint account. Retry to reconcile it.",
        )

    account.customer_code = str(customer["customer_code"])
    account.account_number = str(moniepoint["account_number"])
    account.account_name = str(moniepoint.get("account_name") or "")[:200] or None
    account.bank_name = str(moniepoint.get("bank_name") or "")[:150] or None
    account.is_sandbox = (
        moniepoint.get("is_sandbox")
        if isinstance(moniepoint.get("is_sandbox"), bool)
        else settings.TOPIFY_API_KEY.startswith("sk_test_")
    )
    account.status = "active" if moniepoint.get("is_active") is True else "pending"
    account.provider_metadata = {
        "provider": "moniepoint",
        "is_sandbox": account.is_sandbox,
    }
    db.commit()
    db.refresh(account)
    if account.status != "active":
        raise HTTPException(
            status_code=502,
            detail="Topify has not confirmed the account as active. Retry later to reconcile it.",
        )
    return {"success": True, "data": _account_view(account)}


@router.get("/accounts/me")
def get_my_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.scalar(
        select(TopifyAccount).where(TopifyAccount.user_id == current_user.id)
    )
    if not account:
        raise HTTPException(status_code=404, detail="Topify account not found.")
    return {"success": True, "data": _account_view(account)}


@router.get("/accounts/me/provider")
def get_my_provider_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_enabled()
    account = db.scalar(
        select(TopifyAccount).where(TopifyAccount.user_id == current_user.id)
    )
    if not account or not account.customer_code:
        raise HTTPException(
            status_code=404, detail="Topify customer account is not provisioned."
        )
    try:
        accounts = TopifyClient().get_customer_accounts(account.customer_code)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Topify account retrieval is temporarily unavailable.",
        ) from exc
    return {
        "success": True,
        "data": [
            item
            for item in accounts
            if str(item.get("provider", "")).lower() in {"moniepoint", "30901"}
        ],
    }


def _validate_verified_charge(
    event_data: dict, verified: dict
) -> tuple[str, int, int, int]:
    reference = event_data.get("reference")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 150:
        raise ValueError("Invalid payment reference.")
    if str(event_data.get("currency", "")).upper() != "NGN":
        raise ValueError("Unsupported payment currency.")
    if str(event_data.get("status", "")).lower() != "success":
        raise ValueError("Webhook payment is not successful.")

    amount_kobo = parse_kobo(event_data.get("amount"))
    fee_kobo = parse_kobo(event_data.get("fee"), allow_zero=True)
    net_kobo = amount_kobo - fee_kobo
    if net_kobo <= 0:
        raise ValueError("Net settlement amount must be positive.")

    verified_reference = verified.get("reference")
    verified_amount = parse_kobo(verified.get("amount"))
    verified_fee = parse_kobo(verified.get("fee"), allow_zero=True)
    verified_status = str(verified.get("status", "")).lower()
    if verified_status != "success":
        raise RuntimeError("Topify has not confirmed the payment yet.")
    if (
        verified_reference != reference
        or verified_amount != amount_kobo
        or verified_fee != fee_kobo
    ):
        raise ValueError("Topify verification did not match the webhook.")
    return reference, amount_kobo, fee_kobo, net_kobo


def _find_account_for_event(db: Session, event_data: dict) -> TopifyAccount | None:
    customer = (
        event_data.get("customer")
        if isinstance(event_data.get("customer"), dict)
        else {}
    )
    virtual_account = (
        event_data.get("virtual_account")
        if isinstance(event_data.get("virtual_account"), dict)
        else {}
    )
    customer_code = customer.get("customer_code") or event_data.get("customer_code")
    account_number = virtual_account.get("account_number") or event_data.get(
        "account_number"
    )
    filters = []
    if customer_code:
        filters.append(TopifyAccount.customer_code == str(customer_code))
    if account_number:
        filters.append(TopifyAccount.account_number == str(account_number))
    if not filters:
        return None
    return db.scalar(select(TopifyAccount).where(or_(*filters)))


def _credit_verified_charge(
    db: Session,
    *,
    account: TopifyAccount,
    event_data: dict,
    verified: dict,
    delivery_id: str,
) -> str:
    reference, amount_kobo, fee_kobo, net_kobo = _validate_verified_charge(
        event_data, verified
    )
    local_reference = topify_transaction_key(reference)
    existing = db.scalar(
        select(Transaction)
        .where(Transaction.reference == local_reference)
        .with_for_update()
    )
    net_amount = kobo_to_naira(net_kobo)
    if existing:
        if (
            existing.provider != "topify"
            or existing.provider_reference != reference
            or existing.wallet_id != account.wallet_id
            or existing.amount != net_amount
            or existing.currency.upper() != "NGN"
        ):
            raise ValueError(
                "Payment reference conflicts with an existing ledger transaction."
            )
        return "duplicate"

    wallet = db.scalar(
        select(Wallet).where(Wallet.id == account.wallet_id).with_for_update()
    )
    if (
        not wallet
        or wallet.status.lower() != "active"
        or wallet.currency.upper() != "NGN"
    ):
        raise ValueError("The linked wallet is not available for a credit.")

    transaction = WalletService.credit(
        db,
        wallet_id=wallet.id,
        amount=net_amount,
        reference=local_reference,
        transaction_type="deposit",
        provider="topify",
        provider_reference=reference,
        description="Topify Moniepoint wallet deposit, net of provider fee",
    )
    transaction.provider_metadata = {
        **(transaction.provider_metadata or {}),
        "topify": {
            "event": "charge.success",
            "delivery_id": delivery_id,
            "amount_kobo": amount_kobo,
            "fee_kobo": fee_kobo,
            "net_amount_kobo": net_kobo,
            "currency": "NGN",
            "paid_at": event_data.get("paid_at")
            if isinstance(event_data.get("paid_at"), str)
            else None,
        },
    }
    return "credited"


def _record_event(
    db: Session,
    *,
    delivery_id: str,
    event_type: str,
    event_data: dict,
    status_value: str,
) -> TopifyWebhookEvent:
    event = TopifyWebhookEvent(
        id=uuid.uuid4(),
        delivery_id=delivery_id,
        event_type=event_type,
        provider_reference=(
            str(event_data["reference"])
            if isinstance(event_data.get("reference"), str)
            else None
        ),
        status=status_value,
        safe_metadata=safe_event_metadata(event_type, event_data),
        processed_at=datetime.now(UTC),
    )
    db.add(event)
    return event


def _apply_non_credit_event(
    db: Session, *, event_type: str, event_data: dict, delivery_id: str
) -> str:
    if event_type == "customer.virtual_account.created":
        account = _find_account_for_event(db, event_data)
        if not account:
            # If Topify sends the creation notification before the reserve
            # response, link it by the registered email stored in our request.
            customer = (
                event_data.get("customer")
                if isinstance(event_data.get("customer"), dict)
                else {}
            )
            email = customer.get("email") or event_data.get("email")
            if isinstance(email, str):
                account = db.scalar(
                    select(TopifyAccount)
                    .join(User, User.id == TopifyAccount.user_id)
                    .where(User.email == email)
                )
        if account:
            customer = (
                event_data.get("customer")
                if isinstance(event_data.get("customer"), dict)
                else {}
            )
            virtual_account = (
                event_data.get("virtual_account")
                if isinstance(event_data.get("virtual_account"), dict)
                else {}
            )
            account.customer_code = (
                str(
                    customer.get("customer_code")
                    or event_data.get("customer_code")
                    or account.customer_code
                    or ""
                )
                or None
            )
            account.account_number = (
                str(
                    virtual_account.get("account_number")
                    or event_data.get("account_number")
                    or account.account_number
                    or ""
                )
                or None
            )
            account.account_name = (
                str(
                    virtual_account.get("account_name")
                    or event_data.get("account_name")
                    or account.account_name
                    or ""
                )[:200]
                or None
            )
            account.bank_name = (
                str(
                    virtual_account.get("bank_name")
                    or event_data.get("bank_name")
                    or account.bank_name
                    or ""
                )[:150]
                or None
            )
            account.status = (
                "active"
                if account.account_number and account.customer_code
                else "pending"
            )
            return "account_updated"
        return "review"

    if event_type == "transaction.reversed":
        reference = event_data.get("reference")
        if not isinstance(reference, str) or not reference:
            return "review"
        transaction = db.scalar(
            select(Transaction)
            .where(
                Transaction.provider == "topify",
                Transaction.provider_reference == reference,
                Transaction.transaction_type == "deposit",
            )
            .with_for_update()
        )
        if not transaction:
            return "review"
        if transaction.status == "reversed":
            return "duplicate"
        transaction.status = "reversed"
        transaction.provider_metadata = {
            **(transaction.provider_metadata or {}),
            "topify_reversal": {
                "event": event_type,
                "delivery_id": delivery_id,
                "received_at": datetime.now(UTC).isoformat(),
                "balance_adjusted": False,
            },
        }
        return "reversed_without_balance_change"

    if event_type == "charge.failed":
        return "failed"
    if event_type == "wallet.funded":
        # Topify emits this alongside charge.success. Only the verified charge
        # event is authoritative for ledger crediting.
        return "acknowledged_without_credit"
    return "ignored"


def _process_webhook_event(
    db: Session,
    *,
    delivery_id: str,
    event_type: str,
    event_data: dict,
    verified: dict | None = None,
) -> dict:
    existing_delivery = db.scalar(
        select(TopifyWebhookEvent).where(TopifyWebhookEvent.delivery_id == delivery_id)
    )
    if existing_delivery:
        return {"status": "already_processed", "delivery_id": delivery_id}

    event_row = _record_event(
        db,
        delivery_id=delivery_id,
        event_type=event_type,
        event_data=event_data,
        status_value="received",
    )
    db.flush()

    if event_type == "charge.success":
        account = _find_account_for_event(db, event_data)
        if not account:
            event_row.status = "review"
        elif verified is None:
            raise RuntimeError("Topify payment verification is required.")
        else:
            try:
                event_row.status = _credit_verified_charge(
                    db,
                    account=account,
                    event_data=event_data,
                    verified=verified,
                    delivery_id=delivery_id,
                )
            except (TypeError, ValueError):
                event_row.status = "review"
                event_row.safe_metadata = {
                    **(event_row.safe_metadata or {}),
                    "review_reason": "verification_mismatch",
                }
    elif event_type in SUPPORTED_EVENTS:
        event_row.status = _apply_non_credit_event(
            db,
            event_type=event_type,
            event_data=event_data,
            delivery_id=delivery_id,
        )
    else:
        event_row.status = "ignored"

    event_row.processed_at = datetime.now(UTC)
    db.commit()
    return {"status": event_row.status, "delivery_id": delivery_id}


@router.post("/webhooks", status_code=status.HTTP_200_OK)
async def topify_webhook(
    request: Request,
    topify_signature: str | None = Header(
        default=None,
        alias="X-Topify-Signature",
    ),
    topify_event: str | None = Header(
        default=None,
        alias="X-Topify-Event",
    ),
    topify_delivery: str | None = Header(
        default=None,
        alias="X-Topify-Delivery",
    ),
):
    if not settings.TOPIFY_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Topify webhook processing is disabled.",
        )

    raw_body = await request.body()

    if not verify_webhook_signature(raw_body, topify_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid Topify webhook signature.",
        )

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Topify webhook JSON.",
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid Topify webhook payload.",
        )

    event_type = payload.get("event")
    event_data = payload["data"]

    if not isinstance(event_type, str) or event_type != topify_event:
        raise HTTPException(
            status_code=400,
            detail="Topify event header does not match the payload.",
        )

    if not topify_delivery or len(topify_delivery) > 150:
        raise HTTPException(
            status_code=400,
            detail="A valid Topify delivery ID is required.",
        )

    db: Session = SessionLocal()

    try:
        # Check whether this exact webhook delivery was already recorded.
        existing_delivery = db.scalar(
            select(TopifyWebhookEvent).where(
                TopifyWebhookEvent.delivery_id == topify_delivery
            )
        )

        if existing_delivery:
            return {
                "status": "already_processed",
                "delivery_id": topify_delivery,
            }

        verified = None
        reference = event_data.get("reference")

        # Only charge.success events can credit the wallet.
        if event_type == "charge.success":
            if not isinstance(reference, str) or not reference.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Topify payment reference is missing.",
                )

            account = _find_account_for_event(db, event_data)

            # Release the database transaction before contacting Topify.
            db.rollback()

            if not account:
                event_row = _record_event(
                    db,
                    delivery_id=topify_delivery,
                    event_type=event_type,
                    event_data=event_data,
                    status_value="review",
                )

                event_row.processed_at = datetime.now(UTC)
                db.commit()

                return {
                    "status": "review",
                    "delivery_id": event_row.delivery_id,
                }

            try:
                verified = await run_in_threadpool(
                    TopifyClient(timeout=3.5).verify_transaction,
                    reference,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Topify verification is temporarily unavailable; "
                        "retry this webhook."
                    ),
                ) from exc

        try:
            return _process_webhook_event(
                db,
                delivery_id=topify_delivery,
                event_type=event_type,
                event_data=event_data,
                verified=verified,
            )

        except RuntimeError as exc:
            db.rollback()

            raise HTTPException(
                status_code=502,
                detail=(
                    "Topify has not confirmed the payment yet; "
                    "retry this webhook."
                ),
            ) from exc

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        # A database integrity conflict is not automatically a duplicate.
        # Roll back first, then verify whether this delivery ID exists.
        db.rollback()

        existing_delivery = db.scalar(
            select(TopifyWebhookEvent).where(
                TopifyWebhookEvent.delivery_id == topify_delivery
            )
        )

        if existing_delivery:
            return {
                "status": "already_processed",
                "delivery_id": topify_delivery,
            }

        # If the delivery ID does not exist, this is another database
        # integrity conflict. Do not acknowledge it as processed.
        logger.exception(
            "Topify webhook database conflict; delivery_id=%s",
            topify_delivery,
        )

        raise HTTPException(
            status_code=409,
            detail="Topify webhook conflicts with an existing ledger record.",
        )

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Topify webhook processing failed; delivery_id=%s",
            topify_delivery,
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to process Topify webhook.",
        ) from exc

    finally:
        db.close()

@router.get("/transactions/{reference}/verify")
def verify_my_transaction(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_enabled()
    if not reference or len(reference) > 150:
        raise HTTPException(status_code=400, detail="Invalid Topify reference.")
    transaction = db.scalar(
        select(Transaction)
        .join(Wallet, Wallet.id == Transaction.wallet_id)
        .where(
            Transaction.provider == "topify",
            Transaction.provider_reference == reference,
            Transaction.transaction_type == "deposit",
            Wallet.user_id == current_user.id,
        )
    )
    if not transaction:
        raise HTTPException(
            status_code=404, detail="Topify transaction not found for this wallet."
        )
    db.rollback()
    try:
        verified = TopifyClient().verify_transaction(reference)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail="Topify verification is temporarily unavailable."
        ) from exc
    topify_data = (transaction.provider_metadata or {}).get("topify", {})
    try:
        verified_reference = verified.get("reference")
        verified_amount = parse_kobo(verified.get("amount"))
        verified_fee = parse_kobo(verified.get("fee"), allow_zero=True)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Topify verification response is invalid."
        ) from exc
    verified_status = str(verified.get("status", "")).lower()
    if (
        verified_reference != reference
        or verified_status not in {"success", "reversed"}
        or verified_amount != topify_data.get("amount_kobo")
        or verified_fee != topify_data.get("fee_kobo")
    ):
        raise HTTPException(
            status_code=409,
            detail="Topify verification does not match the recorded payment.",
        )
    if verified_status == "reversed" and transaction.status != "reversed":
        transaction.status = "reversed"
        transaction.provider_metadata = {
            **(transaction.provider_metadata or {}),
            "topify_reversal": {
                "source": "provider_verification",
                "balance_adjusted": False,
            },
        }
        db.commit()
    return {
        "success": True,
        "data": {
            "reference": reference,
            "status": transaction.status,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "provider_status": verified.get("status"),
        },
    }


@router.get("/admin/webhook-events")
def list_webhook_events(
    status_filter: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 200.")
    query = select(TopifyWebhookEvent).order_by(TopifyWebhookEvent.received_at.desc())
    if status_filter:
        query = query.where(TopifyWebhookEvent.status == status_filter)
    rows = db.scalars(query.limit(limit)).all()
    return {
        "items": [
            {
                "delivery_id": row.delivery_id,
                "event": row.event_type,
                "reference": row.provider_reference,
                "status": row.status,
                "safe_metadata": row.safe_metadata,
                "received_at": row.received_at,
                "processed_at": row.processed_at,
            }
            for row in rows
        ]
    }


@router.post("/admin/transactions/{reference}/reconcile")
def reconcile_topify_transaction(
    reference: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    _require_enabled()
    if not reference or len(reference) > 150:
        raise HTTPException(status_code=400, detail="Invalid Topify reference.")
    event = db.scalar(
        select(TopifyWebhookEvent)
        .where(
            TopifyWebhookEvent.provider_reference == reference,
            TopifyWebhookEvent.event_type == "charge.success",
            TopifyWebhookEvent.status == "review",
        )
        .order_by(TopifyWebhookEvent.received_at.desc())
        .limit(1)
    )
    if not event:
        raise HTTPException(status_code=404, detail="Topify review event not found.")
    delivery_id = event.delivery_id
    event_metadata = dict(event.safe_metadata or {})
    db.rollback()

    try:
        verified = TopifyClient().verify_transaction(reference)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail="Topify verification is temporarily unavailable."
        ) from exc

    db_event = db.scalar(
        select(TopifyWebhookEvent)
        .where(TopifyWebhookEvent.delivery_id == delivery_id)
        .with_for_update()
    )
    if not db_event or db_event.status != "review":
        raise HTTPException(
            status_code=409, detail="Topify review event has already changed."
        )
    customer_code = event_metadata.get("customer_code")
    account = (
        db.scalar(
            select(TopifyAccount)
            .where(TopifyAccount.customer_code == customer_code)
            .with_for_update()
        )
        if isinstance(customer_code, str)
        else None
    )
    if not account:
        raise HTTPException(
            status_code=409,
            detail="No ONTIME account matches the Topify customer code.",
        )

    event_data = {
        "reference": reference,
        "amount": event_metadata.get("amount_kobo"),
        "fee": event_metadata.get("fee_kobo"),
        "currency": event_metadata.get("currency"),
        "status": event_metadata.get("provider_status"),
        "paid_at": event_metadata.get("paid_at"),
        "customer": {"customer_code": customer_code},
    }
    try:
        result = _credit_verified_charge(
            db,
            account=account,
            event_data=event_data,
            verified=verified,
            delivery_id=delivery_id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Topify payment still does not match; event remains under review.",
        ) from exc
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Topify has not confirmed the payment yet; retry reconciliation later.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db_event = db.scalar(
        select(TopifyWebhookEvent)
        .where(TopifyWebhookEvent.delivery_id == delivery_id)
        .with_for_update()
    )
    if db_event:
        db_event.status = result
        db_event.processed_at = datetime.now(UTC)
    db.commit()
    return {"status": result, "reference": reference}
