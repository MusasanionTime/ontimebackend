from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin
from app.database.database import get_db
from app.models.admin import Admin
from app.models.admin_audit_log import AdminAuditLog
from app.schemas.admin_audit import (
    AdminAuditLogDetailResponse,
    AdminAuditLogListItem,
    AdminAuditLogListResponse,
)

router = APIRouter(
    prefix="/admin/audit",
    tags=["Admin Audit"],
)


@router.get(
    "/logs",
    response_model=AdminAuditLogListResponse,
)
def admin_list_audit_logs(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    admin_id: str | None = None,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page must be greater than or equal to 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page size must be between 1 and 100",
        )

    query = (
        select(AdminAuditLog, Admin)
        .join(Admin, AdminAuditLog.admin_id == Admin.id)
    )

    if search:
        search_term = f"%{search.strip()}%"

        query = query.where(
            (AdminAuditLog.action.ilike(search_term))
            | (AdminAuditLog.resource_type.ilike(search_term))
            | (AdminAuditLog.resource_id.ilike(search_term))
            | (AdminAuditLog.description.ilike(search_term))
            | (Admin.email.ilike(search_term))
            | (Admin.first_name.ilike(search_term))
            | (Admin.last_name.ilike(search_term))
        )

    if action:
        query = query.where(
            AdminAuditLog.action == action
        )

    if resource_type:
        query = query.where(
            AdminAuditLog.resource_type == resource_type
        )

    if admin_id:
        query = query.where(
            AdminAuditLog.admin_id == admin_id
        )

    rows = db.execute(
        query.order_by(
            AdminAuditLog.created_at.desc()
        )
    ).all()

    total = len(rows)

    offset = (page - 1) * page_size

    paginated_rows = rows[
        offset:offset + page_size
    ]

    total_pages = (
        (total + page_size - 1) // page_size
        if total > 0
        else 0
    )

    items = [
        AdminAuditLogListItem(
            id=audit_log.id,
            admin_id=audit_log.admin_id,
            admin_email=audit_admin.email,
            admin_first_name=audit_admin.first_name,
            admin_last_name=audit_admin.last_name,
            action=audit_log.action,
            resource_type=audit_log.resource_type,
            resource_id=audit_log.resource_id,
            description=audit_log.description,
            ip_address=audit_log.ip_address,
            user_agent=audit_log.user_agent,
            extra_data=audit_log.extra_data,
            created_at=audit_log.created_at,
        )
        for audit_log, audit_admin in paginated_rows
    ]

    return AdminAuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/logs/{audit_log_id}",
    response_model=AdminAuditLogDetailResponse,
)
def admin_get_audit_log(
    audit_log_id: str,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    result = db.execute(
        select(AdminAuditLog, Admin)
        .join(
            Admin,
            AdminAuditLog.admin_id == Admin.id,
        )
        .where(
            AdminAuditLog.id == audit_log_id
        )
    ).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found",
        )

    audit_log, audit_admin = result

    return AdminAuditLogDetailResponse(
        id=audit_log.id,
        admin_id=audit_log.admin_id,
        admin_email=audit_admin.email,
        admin_first_name=audit_admin.first_name,
        admin_last_name=audit_admin.last_name,
        action=audit_log.action,
        resource_type=audit_log.resource_type,
        resource_id=audit_log.resource_id,
        description=audit_log.description,
        ip_address=audit_log.ip_address,
        user_agent=audit_log.user_agent,
        extra_data=audit_log.extra_data,
        created_at=audit_log.created_at,
    )