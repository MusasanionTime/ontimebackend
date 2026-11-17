import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.admin import Admin
from app.models.commission import CommissionConfiguration, CommissionReversal, PurchaseCommission
from app.models.platform_wallet import PlatformWallet
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.platform_wallet.service import (
    credit_platform_wallet_system,
    debit_platform_wallet_system,
    get_or_create_platform_wallet,
)


SERVICE_KEYS = ("airtime", "data", "electricity", "result_checker")
CENT = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_configuration(db: Session, service_key: str, at: datetime | None = None) -> CommissionConfiguration | None:
    at = at or utc_now()
    return db.scalar(
        select(CommissionConfiguration)
        .where(
            CommissionConfiguration.service_key == service_key,
            CommissionConfiguration.effective_from <= at,
            or_(CommissionConfiguration.effective_until.is_(None), CommissionConfiguration.effective_until > at),
        )
        .order_by(CommissionConfiguration.effective_from.desc())
        .limit(1)
    )


def calculate_commission(
    purchase_amount: Decimal,
    calculation_type: str,
    calculation_value: Decimal,
    minimum_commission: Decimal | None = None,
    maximum_commission: Decimal | None = None,
) -> Decimal:
    """Calculate a platform-only commission using Decimal and cent rounding."""
    amount = Decimal(str(purchase_amount))
    value = Decimal(str(calculation_value))
    if not amount.is_finite() or amount <= 0 or not value.is_finite() or value <= 0:
        raise ValueError("Purchase amount and commission value must be positive finite decimals.")
    if calculation_type == "percentage":
        if value > 100:
            raise ValueError("Percentage commission value must not exceed 100.")
        result = amount * value / Decimal("100")
    elif calculation_type == "fixed":
        result = value
    else:
        raise ValueError("Unsupported commission calculation type.")
    result = result.quantize(CENT, rounding=ROUND_HALF_UP)
    if minimum_commission is not None:
        result = max(result, Decimal(str(minimum_commission)).quantize(CENT, rounding=ROUND_HALF_UP))
    if maximum_commission is not None:
        result = min(result, Decimal(str(maximum_commission)).quantize(CENT, rounding=ROUND_HALF_UP))
    return result


def record_provider_success(
    db: Session,
    *,
    purchase_transaction_id: uuid.UUID,
    provider: str,
    provider_reference: str | None,
    service_category: str,
) -> None:
    """Durably checkpoint verified provider success before local finalization."""
    transaction = db.scalar(
        select(Transaction).where(Transaction.id == purchase_transaction_id).with_for_update()
    )
    if not transaction:
        raise ValueError("Purchase transaction was not found.")
    if transaction.status == "completed":
        return
    if transaction.status != "pending":
        raise ValueError("Only a pending purchase can record provider success.")
    metadata = dict(transaction.provider_metadata or {})
    metadata.update(
        provider_success_confirmed=True,
        commission_service_category=service_category,
        commission_provider=provider,
        commission_finalization_status="pending",
    )
    transaction.provider_metadata = metadata
    if provider_reference:
        transaction.provider_reference = str(provider_reference)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _post_purchase_commission(
    db: Session,
    *,
    transaction: Transaction,
    service_category: str,
    provider: str,
) -> PurchaseCommission | None:
    existing = db.scalar(
        select(PurchaseCommission)
        .where(PurchaseCommission.source_transaction_id == transaction.id)
        .with_for_update()
    )
    if existing:
        return existing

    global_config = active_configuration(db, "global")
    if not global_config or not global_config.is_enabled:
        return None
    config = active_configuration(db, service_category)
    if not config or not config.is_enabled:
        return None
    if not config.calculation_type or config.commission_value is None:
        raise ValueError("Enabled commission configuration is incomplete.")
    if config.calculation_basis != "customer_purchase_amount":
        raise ValueError("Unsupported commission calculation basis.")

    purchase_amount_raw = (transaction.provider_metadata or {}).get(
        "commission_purchase_amount"
    )
    if purchase_amount_raw is None:
        raise ValueError("Customer purchase amount was not recorded for this transaction.")
    purchase_amount = Decimal(str(purchase_amount_raw))
    amount = calculate_commission(
        purchase_amount,
        config.calculation_type,
        config.commission_value,
        config.minimum_commission,
        config.maximum_commission,
    )
    if amount <= 0:
        return None

    wallet = get_or_create_platform_wallet(db)
    if wallet.status.lower() != "active":
        raise ValueError("Platform wallet is not active.")
    if wallet.currency != transaction.currency:
        raise ValueError("Purchase and platform wallet currencies do not match.")

    reference = f"PCOM-{transaction.id.hex.upper()}"
    ledger_row = credit_platform_wallet_system(
        db,
        amount=amount,
        reference=reference,
        transaction_type="purchase_commission",
        description=f"Purchase commission for {service_category} transaction {transaction.reference}",
    )
    db.add(ledger_row)
    db.flush()

    customer_wallet = db.get(Wallet, transaction.wallet_id)
    if not customer_wallet:
        raise ValueError("Purchase wallet was not found.")
    commission = PurchaseCommission(
        id=uuid.uuid4(),
        reference=reference,
        customer_id=customer_wallet.user_id,
        source_transaction_id=transaction.id,
        configuration_id=config.id,
        platform_transaction_id=ledger_row.id,
        provider=provider,
        service_category=service_category,
        purchase_amount=purchase_amount,
        calculation_type=config.calculation_type,
        calculation_value=config.commission_value,
        calculation_basis=config.calculation_basis,
        commission_amount=amount,
        currency=transaction.currency,
        status="posted",
    )
    db.add(commission)
    metadata = dict(transaction.provider_metadata or {})
    metadata["commission_finalization_status"] = "posted"
    metadata["commission_reference"] = reference
    transaction.provider_metadata = metadata
    return commission


def finalize_confirmed_purchase(
    db: Session,
    *,
    purchase_transaction_id: uuid.UUID,
    service_category: str | None = None,
    provider: str | None = None,
) -> PurchaseCommission | None:
    """Finalize provider-confirmed purchase and optional commission atomically."""
    transaction = db.scalar(
        select(Transaction).where(Transaction.id == purchase_transaction_id).with_for_update()
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="Purchase transaction not found.")
    if transaction.status == "completed":
        return db.scalar(
            select(PurchaseCommission).where(PurchaseCommission.source_transaction_id == transaction.id)
        )
    if transaction.status != "pending" or not (transaction.provider_metadata or {}).get("provider_success_confirmed"):
        raise HTTPException(status_code=409, detail="Purchase does not have a confirmed provider success to finalize.")

    metadata = dict(transaction.provider_metadata or {})
    category = service_category or metadata.get("commission_service_category")
    provider_name = provider or metadata.get("commission_provider") or transaction.provider or "unknown"
    if category not in SERVICE_KEYS:
        raise HTTPException(status_code=409, detail="Purchase service category is not eligible for commission processing.")

    transaction.status = "completed"
    commission = _post_purchase_commission(
        db,
        transaction=transaction,
        service_category=category,
        provider=provider_name,
    )
    metadata = dict(transaction.provider_metadata or {})
    if commission:
        metadata["commission_finalization_status"] = "posted"
        metadata["commission_reference"] = commission.reference
    else:
        current_global = active_configuration(db, "global")
        category_config = active_configuration(db, category)
        metadata["commission_finalization_status"] = (
            "disabled" if not current_global or not current_global.is_enabled
            else "not_configured" if not category_config or not category_config.is_enabled
            else "no_commission"
        )
    transaction.provider_metadata = metadata
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return commission


def reverse_commission_for_purchase(
    db: Session,
    *,
    purchase_transaction: Transaction,
    refund_reference: str,
    reason: str,
) -> CommissionReversal | None:
    commission = db.scalar(
        select(PurchaseCommission)
        .where(PurchaseCommission.source_transaction_id == purchase_transaction.id)
        .with_for_update()
    )
    if not commission:
        return None
    existing = db.scalar(
        select(CommissionReversal)
        .where(CommissionReversal.commission_id == commission.id)
        .with_for_update()
    )
    if existing:
        return existing
    reference = f"{commission.reference}-REV"
    reversal = CommissionReversal(
        id=uuid.uuid4(),
        commission_id=commission.id,
        reference=reference,
        refund_reference=refund_reference,
        amount=commission.commission_amount,
        status="pending_review",
        reason=reason or "Verified purchase refund",
        review_note="Awaiting platform-wallet funds review.",
    )
    db.add(reversal)
    db.flush()
    _apply_reversal_if_funded(db, commission, reversal)
    return reversal


def _apply_reversal_if_funded(
    db: Session,
    commission: PurchaseCommission,
    reversal: CommissionReversal,
) -> bool:
    if reversal.status == "completed":
        return True
    wallet = db.scalar(select(PlatformWallet).with_for_update())
    if not wallet or wallet.status.lower() != "active" or wallet.balance < reversal.amount:
        reversal.status = "pending_review"
        reversal.review_note = "Platform wallet funds are insufficient; no debit was made."
        commission.status = "reversal_review"
        return False

    if wallet.currency != commission.currency:
        reversal.status = "pending_review"
        reversal.review_note = "Platform wallet currency does not match the commission; no debit was made."
        commission.status = "reversal_review"
        return False
    try:
        ledger_row = debit_platform_wallet_system(
            db,
            amount=reversal.amount,
            reference=reversal.reference,
            transaction_type="purchase_commission_reversal",
            description=f"Reversal of commission {commission.reference}: {reversal.reason}",
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST and "Insufficient" in str(exc.detail):
            reversal.status = "pending_review"
            reversal.review_note = "Platform wallet funds are insufficient; no debit was made."
            commission.status = "reversal_review"
            return False
        raise
    reversal.platform_transaction_id = ledger_row.id
    reversal.status = "completed"
    reversal.review_note = None
    reversal.completed_at = utc_now()
    commission.status = "reversed"
    return True


def retry_commission_reversal(
    db: Session,
    *,
    reversal_id: uuid.UUID,
    admin: Admin,
) -> CommissionReversal:
    reversal = db.scalar(
        select(CommissionReversal).where(CommissionReversal.id == reversal_id).with_for_update()
    )
    if not reversal:
        raise HTTPException(status_code=404, detail="Commission reversal not found.")
    commission = db.scalar(
        select(PurchaseCommission).where(PurchaseCommission.id == reversal.commission_id).with_for_update()
    )
    if not commission:
        raise HTTPException(status_code=404, detail="Commission record not found.")
    if reversal.created_by_admin_id is None:
        reversal.created_by_admin_id = admin.id
    _apply_reversal_if_funded(db, commission, reversal)
    return reversal
