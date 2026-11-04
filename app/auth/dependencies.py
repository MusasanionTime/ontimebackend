from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.database.database import get_db
from app.models.user import User


oauth2_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    print("=== AUTH DEBUG ===")
    print("Authorization scheme:", credentials.scheme)
    print("Authorization credentials received:", bool(credentials.credentials))
    print("Token length:", len(credentials.credentials))
    print("==================")

    token = credentials.credentials

    user_id = decode_access_token(token)

    if not user_id:
        print("AUTH DEBUG: decode_access_token returned None")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    print("AUTH DEBUG: decoded user_id:", user_id)

    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if not user:
        print("AUTH DEBUG: User not found:", user_id)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    print("AUTH DEBUG: User found:", user.email)
    print("AUTH DEBUG: User active:", user.is_active)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    print("AUTH DEBUG: Authentication successful")

    return user