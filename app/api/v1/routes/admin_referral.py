from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.database.database import get_db
from app.models.admin import Admin
from app.models.referral import Referral, ReferralSetting
from app.models.user import User
from app.schemas.referral import ReferralItem, ReferralSettingResponse, ReferralSettingUpdate
from app.referral.service import ensure_settings

router = APIRouter(prefix="/admin/referrals", tags=["Admin Referrals"])


@router.get("/settings", response_model=ReferralSettingResponse)
def get_referral_settings(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    settings = ensure_settings(db)
    db.commit()
    db.refresh(settings)
    return settings


@router.patch("/settings", response_model=ReferralSettingResponse)
def update_referral_settings(
    payload: ReferralSettingUpdate,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    settings = ensure_settings(db)
    for field in ("is_enabled", "reward_type", "reward_amount", "min_qualifying_amount", "reward_on_first_transaction"):
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return settings


@router.get("", response_model=list[ReferralItem])
def list_referrals(
    status_filter: str | None = None,
    referrer_id: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = select(Referral).order_by(Referral.created_at.desc())
    if status_filter:
        query = query.where(Referral.reward_status == status_filter)
    if referrer_id:
        query = query.where(Referral.referrer_user_id == referrer_id)
    return list(db.scalars(query).all())


@router.get("/summary")
def referral_admin_summary(
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(Referral.id))) or 0
    rewarded = db.scalar(select(func.count(Referral.id)).where(Referral.reward_status == "rewarded")) or 0
    pending = db.scalar(select(func.count(Referral.id)).where(Referral.reward_status == "pending")) or 0
    earnings = db.scalar(select(func.coalesce(func.sum(Referral.reward_amount), Decimal("0.00"))).where(Referral.reward_status == "rewarded")) or Decimal("0.00")
    return {"total_referrals": total, "rewarded_referrals": rewarded, "pending_referrals": pending, "total_rewards": earnings}
