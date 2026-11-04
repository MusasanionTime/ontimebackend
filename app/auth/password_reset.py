import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


RESET_TOKEN_EXPIRE_MINUTES = 30


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_password_reset_token(
    db: Session,
    user: User,
) -> tuple[PasswordResetToken, str]:
    token = generate_reset_token()

    token_hash = hash_reset_token(token)

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    )

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    db.add(reset_token)
    db.flush()

    return reset_token, token


def reset_password(
    db: Session,
    token: str,
    new_password: str,
) -> User:
    token_hash = hash_reset_token(token)

    reset_token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
    )

    if not reset_token:
        raise ValueError(
            "Invalid password reset token."
        )

    now = datetime.now(timezone.utc)

    if reset_token.used_at is not None:
        raise ValueError(
            "Password reset token has already been used."
        )

    if reset_token.expires_at <= now:
        raise ValueError(
            "Password reset token has expired."
        )

    user = db.scalar(
        select(User).where(
            User.id == reset_token.user_id
        )
    )

    if not user:
        raise ValueError(
            "User associated with reset token "
            "was not found."
        )

    user.password_hash = hash_password(
        new_password
    )

    reset_token.used_at = now

    db.commit()
    db.refresh(user)

    return user