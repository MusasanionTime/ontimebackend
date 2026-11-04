import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.referral import Referral, ReferralSetting
from app.models.wallet import Wallet
from app.models.transaction import Transaction


def ensure_settings(db: Session) -> ReferralSetting:
    settings = db.get(ReferralSetting, 1)
    if not settings:
        settings = ReferralSetting(id=1)
        db.add(settings)
        db.flush()
    return settings


def generate_referral_code(db: Session) -> str:
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(20):
        code = "ONT" + "".join(secrets.choice(alphabet) for _ in range(7))
        from app.models.user import User
        if not db.scalar(select(User.id).where(User.referral_code == code)):
            return code
    raise RuntimeError("Unable to generate a unique referral code.")


def create_referral_for_user(
    db: Session,
    *,
    referrer_code: str | None,
    referred_user_id: uuid.UUID,
) -> Referral | None:
    if not referrer_code:
        return None

    from app.models.user import User
    referrer = db.scalar(select(User).where(User.referral_code == referrer_code.upper().strip()))
    if not referrer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid referral code.")
    if referrer.id == referred_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot use your own referral code.")

    existing = db.scalar(select(Referral).where(Referral.referred_user_id == referred_user_id))
    if existing:
        return existing

    from app.models.user import User
    referred_user = db.get(User, referred_user_id)
    if referred_user:
        referred_user.referred_by_id = referrer.id

    referral = Referral(
        referrer_user_id=referrer.id,
        referred_user_id=referred_user_id,
        referral_code=referrer.referral_code,
    )
    db.add(referral)
    db.flush()
    return referral


def maybe_reward_first_qualifying_credit(
    db: Session,
    *,
    referred_user_id: uuid.UUID,
    credited_amount: Decimal,
    transaction_type: str,
) -> Referral | None:
    if transaction_type not in {"deposit", "funding", "wallet_funding"}:
        return None

    settings = ensure_settings(db)
    if not settings.is_enabled or not settings.reward_on_first_transaction:
        return None
    if credited_amount < settings.min_qualifying_amount:
        return None

    referral = db.scalar(
        select(Referral)
        .where(
            Referral.referred_user_id == referred_user_id,
            Referral.reward_status == "pending",
        )
        .with_for_update()
    )
    if not referral:
        return None

    if settings.reward_type == "percentage":
        reward = (credited_amount * settings.reward_amount / Decimal("100")).quantize(Decimal("0.01"))
    else:
        reward = settings.reward_amount

    if reward <= Decimal("0.00"):
        return None

    referrer_wallet = db.scalar(
        select(Wallet).where(Wallet.user_id == referral.referrer_user_id).with_for_update()
    )
    if not referrer_wallet or referrer_wallet.status != "active":
        return None

    reference = f"REF-{uuid.uuid4().hex[:20].upper()}"
    before = referrer_wallet.balance
    after = before + reward
    referrer_wallet.balance = after
    db.add(Transaction(
        wallet_id=referrer_wallet.id,
        reference=reference,
        transaction_type="referral_bonus",
        direction="credit",
        amount=reward,
        balance_before=before,
        balance_after=after,
        currency=referrer_wallet.currency,
        status="completed",
        description="Referral reward",
    ))

    referral.reward_amount = reward
    referral.reward_status = "rewarded"
    referral.reward_transaction_reference = reference
    referral.rewarded_at = datetime.now(timezone.utc)
    db.add(referral)
    db.flush()
    return referral
