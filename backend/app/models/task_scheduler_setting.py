from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskSchedulerSetting(Base):
    __tablename__ = "task_scheduler_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    crontab: Mapped[str] = mapped_column(String(64), nullable=False, server_default="0 */2 * * *")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Shanghai")
    # OpenList 网盘目录定时清理（删除 .mp4/.zip/.mkv）
    openlist_cleanup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    openlist_cleanup_path: Mapped[str] = mapped_column(String(512), nullable=False, server_default="")
    openlist_cleanup_crontab: Mapped[str] = mapped_column(String(64), nullable=False, server_default="0 3 * * *")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
