from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.referral import Referral
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.referral import ReferralItem, ReferralSummary

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.get("/me", response_model=ReferralSummary)
def referral_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(Referral.id)).where(Referral.referrer_user_id == current_user.id)) or 0
    rewarded = db.scalar(select(func.count(Referral.id)).where(Referral.referrer_user_id == current_user.id, Referral.reward_status == "rewarded")) or 0
    earnings = db.scalar(select(func.coalesce(func.sum(Referral.reward_amount), 0)).where(Referral.referrer_user_id == current_user.id, Referral.reward_status == "rewarded")) or 0
    return ReferralSummary(referral_code=current_user.referral_code, total_referrals=total, rewarded_referrals=rewarded, total_earnings=earnings)


@router.get("/history", response_model=list[ReferralItem])
def referral_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Referral).where(Referral.referrer_user_id == current_user.id).order_by(Referral.created_at.desc())).all())
