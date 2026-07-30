from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    actor_type: Mapped[str] = mapped_column(String(16), server_default="user", nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(96), index=True, nullable=False)

    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True
    )

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, server_default="1")
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
