from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.database.database import get_db
from app.models.admin import Admin


admin_bearer = HTTPBearer()


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(admin_bearer),
    db: Session = Depends(get_db),
) -> Admin:
    token = credentials.credentials

    admin_id = decode_access_token(token)

    if not admin_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    admin = db.scalar(
        select(Admin).where(Admin.id == admin_id)
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin account not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive",
        )

    return admin


def require_super_admin(
    admin: Admin = Depends(get_current_admin),
) -> Admin:
    if admin.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    return admin