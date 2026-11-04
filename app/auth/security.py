from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password,
    )


def hash_transaction_pin(pin: str) -> str:
    return password_hash.hash(pin)


def verify_transaction_pin(
    pin: str,
    hashed_pin: str,
) -> bool:
    return password_hash.verify(
        pin,
        hashed_pin,
    )


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(subject),
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
        )

        subject = payload.get("sub")

        print("=== JWT DEBUG ===")
        print("JWT decoded successfully")
        print("JWT subject:", subject)
        print("JWT payload:", payload)
        print("=================")

        if not subject:
            print("JWT DEBUG: No 'sub' found in token")
            return None

        return str(subject)

    except jwt.ExpiredSignatureError:
        print("JWT DEBUG: Token has expired")
        return None

    except jwt.InvalidSignatureError:
        print("JWT DEBUG: Invalid signature - SECRET_KEY mismatch")
        return None

    except jwt.InvalidTokenError as exc:
        print("JWT DEBUG: Invalid token:", exc)
        return None