from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, defer

from app.models.audit_log import AuditLog


def _split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def list_audit_logs(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    action: str | None = None,
    category: str | None = None,
    source: str | None = None,
    success: bool | None = None,
) -> tuple[list[tuple[AuditLog, bool]], int]:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    has_detail = (func.coalesce(func.length(AuditLog.detail), 0) > 0)

    stmt: Select = (
        select(AuditLog, has_detail.label("has_detail"))
        .options(defer(AuditLog.detail))
        .order_by(AuditLog.id.desc())
    )

    q_value = (q or "").strip()
    if q_value:
        stmt = stmt.where(
            or_(
                AuditLog.summary.contains(q_value),
                AuditLog.action.contains(q_value),
                AuditLog.target_type.contains(q_value),
                AuditLog.target_id.contains(q_value),
                AuditLog.target_name.contains(q_value),
                AuditLog.actor_username.contains(q_value),
                AuditLog.error_message.contains(q_value),
            )
        )

    actions = _split_multi(action)
    if actions:
        stmt = stmt.where(AuditLog.action.in_(actions))

    categories = _split_multi(category)
    if categories:
        stmt = stmt.where(AuditLog.category.in_(categories))

    source_value = (source or "").strip()
    if source_value == "none":
        stmt = stmt.where(AuditLog.source.is_(None))
    elif source_value:
        sources = _split_multi(source_value)
        if sources:
            stmt = stmt.where(AuditLog.source.in_(sources))

    if success is not None:
        stmt = stmt.where(AuditLog.success.is_(bool(success)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return [(row[0], bool(row[1])) for row in rows], int(total)


def get_audit_log(db: Session, log_id: int) -> AuditLog | None:
    return db.get(AuditLog, log_id)
