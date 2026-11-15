from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, verify_password
from app.database.database import get_db
from app.models.user import User
from app.schemas.login import LoginRequest, LoginResponse
from app.topify.provisioning import provision_topify_account_after_login

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    data: LoginRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.email == data.email)
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(
        data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    access_token = create_access_token(
        subject=str(user.id)
    )

    # The response is sent before this task contacts Topify. Its own session
    # keeps provider failures isolated from authentication and the login DB.
    background_tasks.add_task(
        provision_topify_account_after_login,
        user.id,
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
    )
