"""Audit logging helper — writes to the audit_log table."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def log_audit(
    session: AsyncSession,
    action: str,
    user: str,
    request: Optional[Request] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """Persist an audit log entry.

    Args:
        session: Database session (caller commits).
        action: Action name (e.g., "scan.start", "export.csv").
        user: Username performing the action.
        request: FastAPI request (for source IP extraction).
        resource_type: Optional resource type (e.g., "scan", "ioc_scan").
        resource_id: Optional resource identifier.
        detail: Optional JSONB detail payload.
    """
    source_ip = None
    if request and request.client:
        source_ip = request.client.host

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        action=action,
        user=user,
        source_ip=source_ip,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
    )
    session.add(entry)
    await session.commit()
