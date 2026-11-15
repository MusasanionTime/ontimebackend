"""Safe, retryable Topify Moniepoint account provisioning."""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import SessionLocal
from app.models.topify_account import TopifyAccount
from app.models.user import User
from app.models.wallet import Wallet
from app.topify.client import TopifyClient

logger = logging.getLogger("ontime.payments.topify")

_CLAIM_TIMEOUT = timedelta(minutes=2)
_RETRY_INTERVAL = timedelta(minutes=5)


def _recent(timestamp: datetime | None, *, now: datetime, interval: timedelta) -> bool:
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return now - timestamp < interval


def _moniepoint_account(accounts: list[dict]) -> dict | None:
    return next(
        (
            item
            for item in accounts
            if isinstance(item, dict)
            and str(item.get("provider", "")).lower() in {"moniepoint", "30901"}
        ),
        None,
    )


def ensure_topify_account(
    db: Session,
    user_id: uuid.UUID,
    *,
    client_factory: Callable[..., TopifyClient] = TopifyClient,
) -> dict:
    """Provision once, or poll Topify for an already-known pending customer."""
    if not settings.TOPIFY_ENABLED:
        return {"status": "disabled", "account": None}
    if not settings.TOPIFY_API_KEY or not settings.TOPIFY_BUSINESS_ID:
        return {"status": "not_configured", "account": None}

    user = db.get(User, user_id)
    if not user:
        return {"status": "user_missing", "account": None}

    wallet = db.scalar(
        select(Wallet).where(Wallet.user_id == user.id).with_for_update()
    )
    if (
        not wallet
        or wallet.status.lower() != "active"
        or wallet.currency.upper() != "NGN"
    ):
        return {"status": "wallet_unavailable", "account": None}

    email = (user.email or "").strip()
    phone = (user.phone or "").strip()
    first_name = (user.first_name or "").strip()
    last_name = (user.last_name or "").strip()
    if not email or not phone or not first_name or not last_name:
        return {"status": "profile_incomplete", "account": None}

    now = datetime.now(UTC)
    account = db.scalar(
        select(TopifyAccount)
        .where(TopifyAccount.user_id == user.id)
        .with_for_update()
    )
    created = False
    if not account:
        account = TopifyAccount(
            id=uuid.uuid4(),
            user_id=user.id,
            wallet_id=wallet.id,
            request_email=email,
            request_name=f"{first_name} {last_name}"[:200],
            request_phone=phone,
            bank_code="30901",
            currency="NGN",
            status="pending",
        )
        db.add(account)
        try:
            db.flush()
            created = True
        except IntegrityError:
            db.rollback()
            account = db.scalar(
                select(TopifyAccount)
                .where(TopifyAccount.user_id == user.id)
                .with_for_update()
            )
            if not account:
                return {"status": "in_progress", "account": None}

    if account.status == "active" and account.account_number:
        db.commit()
        return {"status": "active", "account": account}

    if account.status in {"reserving", "checking"} and _recent(
        account.updated_at, now=now, interval=_CLAIM_TIMEOUT
    ):
        db.commit()
        return {"status": "in_progress", "account": account}

    if not created and account.status == "pending" and _recent(
        account.updated_at, now=now, interval=_RETRY_INTERVAL
    ):
        db.commit()
        return {"status": "pending", "account": account}

    action = "checking" if account.customer_code else "reserving"
    account.status = action
    account.updated_at = now
    db.commit()

    try:
        client = client_factory(timeout=8.0)
        if account.customer_code:
            provider_accounts = client.get_customer_accounts(account.customer_code)
            customer_code = account.customer_code
        else:
            response = client.reserve_virtual_account(
                email=account.request_email,
                name=account.request_name,
                phone_number=account.request_phone,
                business_id=settings.TOPIFY_BUSINESS_ID,
            )
            customer = response.get("customer")
            customer = customer if isinstance(customer, dict) else {}
            customer_code = customer.get("customer_code")
            provider_accounts = response.get("accounts")
            provider_accounts = (
                provider_accounts if isinstance(provider_accounts, list) else []
            )
            if isinstance(customer_code, str) and customer_code:
                # Save the provider reference before any further work. Future
                # retries poll this customer instead of reserving again.
                account.customer_code = customer_code[:100]
                account.status = "pending"
                account.updated_at = datetime.now(UTC)
                db.commit()

        moniepoint = _moniepoint_account(provider_accounts)
        if moniepoint:
            account.customer_code = (
                str(customer_code)[:100] if customer_code else account.customer_code
            )
            account.account_number = str(
                moniepoint.get("account_number") or account.account_number or ""
            )[:20] or None
            account.account_name = str(
                moniepoint.get("account_name") or account.account_name or ""
            )[:200] or None
            account.bank_name = str(
                moniepoint.get("bank_name") or account.bank_name or ""
            )[:150] or None
            if isinstance(moniepoint.get("is_sandbox"), bool):
                account.is_sandbox = moniepoint["is_sandbox"]
            elif account.is_sandbox is None:
                account.is_sandbox = settings.TOPIFY_API_KEY.startswith("sk_test_")
            account.provider_metadata = {
                "provider": "moniepoint",
                "is_sandbox": account.is_sandbox,
            }
            account.status = (
                "active"
                if account.account_number
                and account.customer_code
                and moniepoint.get("is_active") is True
                else "pending"
            )
        else:
            account.status = "pending"

        account.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(account)
        return {"status": account.status, "account": account}
    except Exception as exc:  # noqa: BLE001 - provider failures leave retryable state
        db.rollback()
        account = db.scalar(
            select(TopifyAccount).where(TopifyAccount.user_id == user.id)
        )
        if account:
            account.status = "pending"
            account.updated_at = datetime.now(UTC)
            db.commit()
        logger.info(
            "Topify account provisioning deferred: user_id=%s error_type=%s",
            user.id,
            type(exc).__name__,
        )
        return {"status": "pending", "account": account}


def provision_topify_account_after_login(user_id: uuid.UUID) -> None:
    """FastAPI background task; errors must never affect authentication."""
    if not settings.TOPIFY_ENABLED:
        return
    db = SessionLocal()
    try:
        ensure_topify_account(db, user_id)
    except Exception as exc:  # noqa: BLE001 - login must survive any provisioning error
        db.rollback()
        logger.info(
            "Topify login provisioning deferred: user_id=%s error_type=%s",
            user_id,
            type(exc).__name__,
        )
    finally:
        db.close()
