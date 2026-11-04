import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.wallet import Wallet


WALLET_PREFIX = "82"


def generate_wallet_number(db: Session) -> str:
    """Generate a unique internal ONTIME wallet number.

    Customer wallet numbers are internal identifiers; they are not bank
    account numbers and do not require BVN/NIN.
    """
    for _ in range(20):
        candidate = f"{WALLET_PREFIX}{secrets.randbelow(100_000_000):08d}"
        exists = db.scalar(
            select(Wallet.id).where(Wallet.wallet_number == candidate)
        )
        if not exists:
            return candidate

    raise RuntimeError("Unable to generate a unique wallet number.")
