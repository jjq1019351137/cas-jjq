from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_permissions
from app.core.permissions import AUDIT_READ
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogDetailOut, AuditLogItemOut, AuditLogListOut
from app.services import audit as audit_service
from app.services.audit_logs import get_audit_log, list_audit_logs


router = APIRouter()


def _item(row: AuditLog, has_detail: bool) -> AuditLogItemOut:
    return AuditLogItemOut(
        id=row.id,
        created_at=row.created_at,
        actor_type=row.actor_type,
        actor_user_id=row.actor_user_id,
        actor_username=row.actor_username,
        source=row.source,
        source_label=audit_service.source_label(row.source),
        category=row.category,
        category_label=audit_service.category_label(row.category),
        action=row.action,
        action_label=audit_service.action_label(row.action),
        target_type=row.target_type,
        target_id=row.target_id,
        target_name=row.target_name,
        summary=row.summary,
        ip=row.ip,
        success=bool(row.success),
        error_message=row.error_message,
        has_detail=has_detail,
    )


@router.get("", response_model=AuditLogListOut, dependencies=[Depends(require_permissions(AUDIT_READ))])
def get_audit_logs(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    action: str | None = None,
    category: str | None = None,
    source: str | None = None,
    success: bool | None = None,
    db: Session = Depends(get_db),
):
    rows, total = list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        q=q,
        action=action,
        category=category,
        source=source,
        success=success,
    )
    items = [_item(row, has_detail) for row, has_detail in rows]
    return AuditLogListOut(page=page, page_size=page_size, total=total, items=items)


@router.get("/actions", dependencies=[Depends(require_permissions(AUDIT_READ))])
def get_audit_action_registry():
    """返回 action/category/source 注册表，供前端过滤与中文展示。"""
    return audit_service.action_registry()


@router.get("/{log_id}", response_model=AuditLogDetailOut, dependencies=[Depends(require_permissions(AUDIT_READ))])
def get_audit_log_detail(log_id: int, db: Session = Depends(get_db)):
    row = get_audit_log(db, log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="审计日志不存在")
    has_detail = bool(row.detail)
    item = _item(row, has_detail)
    return AuditLogDetailOut(**item.model_dump(), detail=row.detail)
