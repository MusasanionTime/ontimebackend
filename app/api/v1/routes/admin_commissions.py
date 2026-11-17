import math
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin, require_super_admin
from app.commission.service import (
    SERVICE_KEYS,
    active_configuration,
    finalize_confirmed_purchase,
    retry_commission_reversal,
    utc_now,
)
from app.database.database import get_db
from app.models.admin import Admin
from app.models.commission import CommissionConfiguration, CommissionReversal, PurchaseCommission
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.commission import (
    CommissionConfigurationResponse,
    CommissionConfigurationUpdate,
    CommissionOverview,
    CommissionPurchaseReconciliation,
    CommissionReversalItem,
    CommissionReversalPage,
    CommissionSummary,
    PurchaseCommissionItem,
    PurchaseCommissionPage,
)
from app.services.admin_audit import create_admin_audit_log


router = APIRouter(prefix="/admin/commissions", tags=["Admin Purchase Commissions"])
GLOBAL_KEY = "global"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _commission_rows(db: Session, filters: list, *, offset: int | None = None, limit: int | None = None):
    query = (
        select(PurchaseCommission, User, Transaction)
        .join(User, User.id == PurchaseCommission.customer_id)
        .join(Transaction, Transaction.id == PurchaseCommission.source_transaction_id)
        .where(*filters)
        .order_by(PurchaseCommission.created_at.desc())
    )
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return db.execute(query).all()


def _commission_item(commission: PurchaseCommission, customer: User, source: Transaction) -> dict:
    return {
        "id": commission.id,
        "reference": commission.reference,
        "customer_id": commission.customer_id,
        "customer_email": customer.email,
        "customer_name": f"{customer.first_name or ''} {customer.last_name or ''}".strip() or None,
        "source_transaction_id": commission.source_transaction_id,
        "purchase_reference": source.reference,
        "provider_reference": source.provider_reference,
        "configuration_id": commission.configuration_id,
        "platform_transaction_id": commission.platform_transaction_id,
        "provider": commission.provider,
        "service_category": commission.service_category,
        "purchase_amount": commission.purchase_amount,
        "calculation_type": commission.calculation_type,
        "calculation_value": commission.calculation_value,
        "calculation_basis": commission.calculation_basis,
        "commission_amount": commission.commission_amount,
        "currency": commission.currency,
        "status": commission.status,
        "created_at": commission.created_at,
    }


def _reversal_item(row, commission: PurchaseCommission, customer: User, source: Transaction) -> dict:
    return {
        "id": row.id,
        "commission_id": row.commission_id,
        "commission_reference": commission.reference,
        "purchase_reference": source.reference,
        "customer_id": customer.id,
        "customer_email": customer.email,
        "reference": row.reference,
        "refund_reference": row.refund_reference,
        "platform_transaction_id": row.platform_transaction_id,
        "amount": row.amount,
        "status": row.status,
        "reason": row.reason,
        "review_note": row.review_note,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


@router.get("/overview", response_model=CommissionOverview)
def commission_overview(
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = utc_now()
    today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    earned = db.scalar(select(func.coalesce(func.sum(PurchaseCommission.commission_amount), 0)))
    reversed_total = db.scalar(
        select(func.coalesce(func.sum(CommissionReversal.amount), 0)).where(CommissionReversal.status == "completed")
    )
    today_total = db.scalar(
        select(func.coalesce(func.sum(PurchaseCommission.commission_amount), 0)).where(PurchaseCommission.created_at >= today)
    )
    week_total = db.scalar(
        select(func.coalesce(func.sum(PurchaseCommission.commission_amount), 0)).where(PurchaseCommission.created_at >= week)
    )
    month_total = db.scalar(
        select(func.coalesce(func.sum(PurchaseCommission.commission_amount), 0)).where(PurchaseCommission.created_at >= month)
    )
    by_service = db.execute(
        select(
            PurchaseCommission.service_category,
            func.count(PurchaseCommission.id),
            func.coalesce(func.sum(PurchaseCommission.commission_amount), 0),
        ).group_by(PurchaseCommission.service_category).order_by(PurchaseCommission.service_category)
    ).all()
    by_provider = db.execute(
        select(
            PurchaseCommission.provider,
            func.count(PurchaseCommission.id),
            func.coalesce(func.sum(PurchaseCommission.commission_amount), 0),
        ).group_by(PurchaseCommission.provider).order_by(PurchaseCommission.provider)
    ).all()
    reversals_pending = db.scalar(
        select(func.count(CommissionReversal.id)).where(CommissionReversal.status == "pending_review")
    ) or 0
    pending_rows = db.scalars(select(Transaction).where(Transaction.status == "pending")).all()
    pending_finalization = sum(
        1 for row in pending_rows
        if (row.provider_metadata or {}).get("provider_success_confirmed") is True
    )
    total_earned = _money(earned)
    total_reversed = _money(reversed_total)
    return {
        "total_earned": total_earned,
        "total_reversed": total_reversed,
        "net_total": total_earned - total_reversed,
        "today_earned": _money(today_total),
        "week_earned": _money(week_total),
        "month_earned": _money(month_total),
        "posted_count": db.scalar(select(func.count(PurchaseCommission.id))) or 0,
        "reversal_review_count": reversals_pending,
        "pending_finalization_count": pending_finalization,
        "by_service": [
            {"service_category": key, "count": count, "commission_amount": _money(amount)}
            for key, count, amount in by_service
        ],
        "by_provider": [
            {"provider": key, "count": count, "commission_amount": _money(amount)}
            for key, count, amount in by_provider
        ],
    }


@router.get("/transactions", response_model=PurchaseCommissionPage)
def list_commissions(
    service: str | None = None,
    provider: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    filters = []
    if service:
        filters.append(PurchaseCommission.service_category == service)
    if provider:
        filters.append(PurchaseCommission.provider == provider)
    if status_filter:
        filters.append(PurchaseCommission.status == status_filter)
    if date_from:
        filters.append(PurchaseCommission.created_at >= _utc(date_from))
    if date_to:
        filters.append(PurchaseCommission.created_at <= _utc(date_to))
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(PurchaseCommission.reference.ilike(term), Transaction.reference.ilike(term), User.email.ilike(term)))
    total = db.scalar(
        select(func.count(PurchaseCommission.id))
        .join(User, User.id == PurchaseCommission.customer_id)
        .join(Transaction, Transaction.id == PurchaseCommission.source_transaction_id)
        .where(*filters)
    ) or 0
    rows = _commission_rows(db, filters, offset=(page - 1) * page_size, limit=page_size)
    return {
        "items": [_commission_item(*row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/transactions/{commission_id}", response_model=PurchaseCommissionItem)
def get_commission(
    commission_id: UUID,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(PurchaseCommission, User, Transaction)
        .join(User, User.id == PurchaseCommission.customer_id)
        .join(Transaction, Transaction.id == PurchaseCommission.source_transaction_id)
        .where(PurchaseCommission.id == commission_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Commission record not found.")
    return _commission_item(*row)


@router.get("/summary", response_model=CommissionSummary)
def commission_summary(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    service: str | None = None,
    provider: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    filters = []
    if date_from:
        filters.append(PurchaseCommission.created_at >= _utc(date_from))
    if date_to:
        filters.append(PurchaseCommission.created_at <= _utc(date_to))
    if service:
        filters.append(PurchaseCommission.service_category == service)
    if provider:
        filters.append(PurchaseCommission.provider == provider)
    by_day = db.execute(
        select(
            func.date(PurchaseCommission.created_at),
            func.count(PurchaseCommission.id),
            func.coalesce(func.sum(PurchaseCommission.commission_amount), 0),
        ).where(*filters).group_by(func.date(PurchaseCommission.created_at)).order_by(func.date(PurchaseCommission.created_at))
    ).all()
    by_service = db.execute(
        select(PurchaseCommission.service_category, func.count(PurchaseCommission.id), func.coalesce(func.sum(PurchaseCommission.commission_amount), 0))
        .where(*filters).group_by(PurchaseCommission.service_category).order_by(PurchaseCommission.service_category)
    ).all()
    by_provider = db.execute(
        select(PurchaseCommission.provider, func.count(PurchaseCommission.id), func.coalesce(func.sum(PurchaseCommission.commission_amount), 0))
        .where(*filters).group_by(PurchaseCommission.provider).order_by(PurchaseCommission.provider)
    ).all()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "by_day": [{"date": str(day), "count": count, "commission_amount": _money(amount)} for day, count, amount in by_day],
        "by_service": [{"service_category": key, "count": count, "commission_amount": _money(amount)} for key, count, amount in by_service],
        "by_provider": [{"provider": key, "count": count, "commission_amount": _money(amount)} for key, count, amount in by_provider],
    }


@router.get("/settings", response_model=list[CommissionConfigurationResponse])
def commission_settings(
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return list(db.scalars(
        select(CommissionConfiguration).order_by(
            CommissionConfiguration.service_key,
            CommissionConfiguration.revision.desc(),
        )
    ).all())


def _validate_configuration(
    service_key: str,
    payload: CommissionConfigurationUpdate,
    latest: CommissionConfiguration | None,
) -> dict:
    values = {
        "is_enabled": payload.is_enabled,
        "calculation_type": payload.calculation_type if payload.calculation_type is not None else (latest.calculation_type if latest else None),
        "commission_value": payload.commission_value if payload.commission_value is not None else (latest.commission_value if latest else None),
        "calculation_basis": payload.calculation_basis if payload.calculation_basis is not None else (latest.calculation_basis if latest else None),
        "minimum_commission": payload.minimum_commission if payload.minimum_commission is not None else (latest.minimum_commission if latest else None),
        "maximum_commission": payload.maximum_commission if payload.maximum_commission is not None else (latest.maximum_commission if latest else None),
    }
    if service_key == GLOBAL_KEY:
        if any(values[key] is not None for key in ("calculation_type", "commission_value", "calculation_basis", "minimum_commission", "maximum_commission")):
            raise HTTPException(status_code=422, detail="Global configuration only controls the master enable switch.")
        return values
    if service_key not in SERVICE_KEYS:
        raise HTTPException(status_code=404, detail="Unsupported commission service category.")
    if values["is_enabled"]:
        if not values["calculation_type"] or values["commission_value"] is None or not values["calculation_basis"]:
            raise HTTPException(status_code=422, detail="An enabled service needs an approved calculation type, value, and basis.")
        if values["calculation_type"] == "percentage" and values["commission_value"] > Decimal("100"):
            raise HTTPException(status_code=422, detail="Percentage commission cannot exceed 100.")
    minimum = values["minimum_commission"]
    maximum = values["maximum_commission"]
    if minimum is not None and maximum is not None and minimum > maximum:
        raise HTTPException(status_code=422, detail="Minimum commission cannot exceed maximum commission.")
    return values


@router.put("/settings/{service_key}", response_model=CommissionConfigurationResponse)
def update_commission_settings(
    service_key: str,
    payload: CommissionConfigurationUpdate,
    request: Request,
    admin: Admin = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if service_key != GLOBAL_KEY and service_key not in SERVICE_KEYS:
        raise HTTPException(status_code=404, detail="Unsupported commission service category.")
    latest = db.scalar(
        select(CommissionConfiguration)
        .where(CommissionConfiguration.service_key == service_key)
        .order_by(CommissionConfiguration.revision.desc())
        .limit(1)
        .with_for_update()
    )
    now = utc_now()
    effective_from = _utc(payload.effective_from) if payload.effective_from else now
    if effective_from < now:
        raise HTTPException(status_code=422, detail="Commission changes cannot be backdated.")
    if latest and effective_from <= _utc(latest.effective_from):
        raise HTTPException(status_code=409, detail="A newer configuration revision already exists.")
    values = _validate_configuration(service_key, payload, latest)
    old_values = {
        "is_enabled": latest.is_enabled if latest else False,
        "calculation_type": latest.calculation_type if latest else None,
        "commission_value": str(latest.commission_value) if latest and latest.commission_value is not None else None,
        "calculation_basis": latest.calculation_basis if latest else None,
        "minimum_commission": str(latest.minimum_commission) if latest and latest.minimum_commission is not None else None,
        "maximum_commission": str(latest.maximum_commission) if latest and latest.maximum_commission is not None else None,
        "effective_from": latest.effective_from.isoformat() if latest else None,
    }
    if service_key == GLOBAL_KEY and values["is_enabled"]:
        has_enabled_service = any(
            (row := active_configuration(db, key, effective_from)) is not None
            and row.is_enabled
            and row.calculation_type
            and row.commission_value is not None
            and row.calculation_basis == "customer_purchase_amount"
            for key in SERVICE_KEYS
        )
        if not has_enabled_service:
            raise HTTPException(status_code=422, detail="Configure and approve at least one service before enabling global commissions.")

    if latest:
        future = db.scalar(
            select(CommissionConfiguration.id).where(
                CommissionConfiguration.service_key == service_key,
                CommissionConfiguration.effective_from >= effective_from,
            ).limit(1)
        )
        if future:
            raise HTTPException(status_code=409, detail="A future configuration revision already exists.")
        latest.effective_until = effective_from
        revision = latest.revision + 1
    else:
        revision = 1
    row = CommissionConfiguration(
        id=uuid.uuid4(),
        service_key=service_key,
        revision=revision,
        **values,
        effective_from=effective_from,
        reason=payload.reason,
        created_by_admin_id=admin.id,
    )
    db.add(row)
    create_admin_audit_log(
        db,
        admin,
        "PURCHASE_COMMISSION_CONFIG_UPDATED",
        "purchase_commission_configuration",
        str(row.id),
        "Purchase commission configuration revision created",
        request,
        {
            "service_key": service_key,
            "revision": revision,
            "reason": payload.reason,
            "old_values": old_values,
            "new_values": {
                "is_enabled": values["is_enabled"],
                "calculation_type": values["calculation_type"],
                "commission_value": str(values["commission_value"]) if values["commission_value"] is not None else None,
                "calculation_basis": values["calculation_basis"],
                "minimum_commission": str(values["minimum_commission"]) if values["minimum_commission"] is not None else None,
                "maximum_commission": str(values["maximum_commission"]) if values["maximum_commission"] is not None else None,
                "effective_from": effective_from.isoformat(),
            },
        },
    )
    try:
        db.commit()
        db.refresh(row)
        return row
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save commission configuration.") from exc


@router.get("/reversals", response_model=CommissionReversalPage)
def list_commission_reversals(
    status_filter: str | None = Query(None, alias="status"),
    service: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    filters = []
    if status_filter:
        filters.append(CommissionReversal.status == status_filter)
    if service:
        filters.append(PurchaseCommission.service_category == service)
    if date_from:
        filters.append(CommissionReversal.created_at >= _utc(date_from))
    if date_to:
        filters.append(CommissionReversal.created_at <= _utc(date_to))
    base = (
        select(CommissionReversal, PurchaseCommission, User, Transaction)
        .join(PurchaseCommission, PurchaseCommission.id == CommissionReversal.commission_id)
        .join(User, User.id == PurchaseCommission.customer_id)
        .join(Transaction, Transaction.id == PurchaseCommission.source_transaction_id)
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(CommissionReversal.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_reversal_item(*row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.post("/reversals/{reversal_id}/retry", response_model=CommissionReversalItem)
def retry_reversal(
    reversal_id: UUID,
    request: Request,
    admin: Admin = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        row = retry_commission_reversal(db, reversal_id=reversal_id, admin=admin)
        commission = db.get(PurchaseCommission, row.commission_id)
        source = db.get(Transaction, commission.source_transaction_id) if commission else None
        customer = db.get(User, commission.customer_id) if commission else None
        if not commission or not source or not customer:
            raise HTTPException(status_code=404, detail="Commission reversal source is missing.")
        create_admin_audit_log(
            db, admin, "PURCHASE_COMMISSION_REVERSAL_RETRY", "purchase_commission_reversal",
            str(row.id), "Super admin retried a pending commission reversal", request,
            {"reference": row.reference, "status": row.status},
        )
        db.commit()
        return _reversal_item(row, commission, customer, source)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to retry commission reversal.") from exc


@router.get("/reconciliation", response_model=list[CommissionPurchaseReconciliation])
def pending_purchase_finalization(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Transaction).where(Transaction.status == "pending").order_by(Transaction.created_at.desc())
    ).all()
    confirmed = [
        row for row in rows
        if (row.provider_metadata or {}).get("provider_success_confirmed") is True
    ]
    start = (page - 1) * page_size
    return [
        {
            "transaction_id": row.id,
            "reference": row.reference,
            "provider_reference": row.provider_reference,
            "provider": (row.provider_metadata or {}).get("commission_provider") or row.provider,
            "service_category": (row.provider_metadata or {}).get("commission_service_category", "unknown"),
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in confirmed[start:start + page_size]
    ]


@router.post("/reconciliation/{transaction_id}/finalize")
def finalize_purchase_reconciliation(
    transaction_id: UUID,
    request: Request,
    admin: Admin = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        commission = finalize_confirmed_purchase(db, purchase_transaction_id=transaction_id)
        create_admin_audit_log(
            db, admin, "PURCHASE_COMMISSION_RECONCILE", "purchase_transaction",
            str(transaction_id), "Super admin finalized a provider-confirmed purchase", request,
            {"commission_reference": commission.reference if commission else None},
        )
        db.commit()
        return {
            "success": True,
            "transaction_id": str(transaction_id),
            "commission_reference": commission.reference if commission else None,
            "status": "completed",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to finalize confirmed purchase.") from exc
