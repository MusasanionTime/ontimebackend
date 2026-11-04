from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.admin import Admin
from app.models.admin_audit_log import AdminAuditLog


def create_admin_audit_log(
    db: Session,
    admin: Admin,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    description: str | None = None,
    request: Request | None = None,
    extra_data: dict[str, Any] | None = None,
) -> AdminAuditLog:
    ip_address = None
    user_agent = None

    if request is not None:
        if request.client:
            ip_address = request.client.host

        user_agent = request.headers.get("user-agent")

    audit_log = AdminAuditLog(
        admin_id=admin.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        extra_data=extra_data,
    )

    db.add(audit_log)
    db.flush()

    return audit_log