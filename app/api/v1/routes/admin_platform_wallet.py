import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.database.database import get_db
from app.models.admin import Admin
from app.models.platform_wallet import PlatformTransaction
from app.platform_wallet.service import get_or_create_platform_wallet, credit_platform_wallet, debit_platform_wallet
from app.schemas.platform_wallet import PlatformWalletAdjustment, PlatformWalletResponse, PlatformWalletTransaction
from app.services.admin_audit import create_admin_audit_log

router = APIRouter(prefix="/admin/platform-wallet", tags=["Admin Platform Wallet"])


@router.get("", response_model=PlatformWalletResponse)
def get_platform_wallet(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    wallet = get_or_create_platform_wallet(db)
    db.commit()
    db.refresh(wallet)
    return wallet


@router.get("/transactions", response_model=list[PlatformWalletTransaction])
def platform_wallet_transactions(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    wallet = get_or_create_platform_wallet(db)
    rows = db.scalars(select(PlatformTransaction).where(PlatformTransaction.platform_wallet_id == wallet.id).order_by(PlatformTransaction.created_at.desc())).all()
    db.commit()
    return list(rows)


@router.post("/credit", response_model=PlatformWalletTransaction, status_code=status.HTTP_201_CREATED)
def credit_platform(
    payload: PlatformWalletAdjustment,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        tx = credit_platform_wallet(db, admin=admin, amount=payload.amount, reference=payload.reference, transaction_type=payload.transaction_type, description=payload.description)
        create_admin_audit_log(db, admin, "PLATFORM_WALLET_CREDIT", "platform_wallet", str(tx.platform_wallet_id), "Platform wallet credited", request, {"amount": str(payload.amount), "reference": payload.reference})
        db.commit()
        db.refresh(tx)
        return tx
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to credit platform wallet.") from exc


@router.post("/debit", response_model=PlatformWalletTransaction, status_code=status.HTTP_201_CREATED)
def debit_platform(
    payload: PlatformWalletAdjustment,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        tx = debit_platform_wallet(db, admin=admin, amount=payload.amount, reference=payload.reference, transaction_type=payload.transaction_type, description=payload.description)
        create_admin_audit_log(db, admin, "PLATFORM_WALLET_DEBIT", "platform_wallet", str(tx.platform_wallet_id), "Platform wallet debited", request, {"amount": str(payload.amount), "reference": payload.reference})
        db.commit()
        db.refresh(tx)
        return tx
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to debit platform wallet.") from exc
