from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.db.drivers.base import DatabaseDriver

_LOCK_ERROR_MARKERS = (
    "lock wait timeout exceeded",   # 1205
    "deadlock found",               # 1213
)


class MySQLDriver(DatabaseDriver):
    name = "mysql"

    @property
    def url(self) -> str:
        return self.settings.database_url

    def connect_args(self) -> dict[str, Any]:
        return {"connect_timeout": int(self.settings.db_connect_timeout_seconds or 10)}

    def engine_kwargs(self, *, for_migrations: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "future": True,
            "pool_pre_ping": True,
            "pool_recycle": int(self.settings.db_pool_recycle_seconds or 3600),
            "pool_size": int(self.settings.db_pool_size or 10),
            "max_overflow": int(self.settings.db_pool_max_overflow or 20),
            "pool_timeout": 30,
        }
        if for_migrations:
            kwargs["pool_size"] = 2
            kwargs["max_overflow"] = 2
        return kwargs

    def prepare_environment(self) -> None:
        os.makedirs(self.settings.resolved_app_data_dir, exist_ok=True)

    def is_lock_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in _LOCK_ERROR_MARKERS)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        parsed = urlparse(self.url)
        if not (parsed.hostname or "").strip():
            errors.append("MySQL 连接缺少主机名（DB_HOST 或 DATABASE_URL 中的 host）")
        if not (parsed.path or "").lstrip("/").strip():
            errors.append("MySQL 连接缺少数据库名（DB_NAME 或 DATABASE_URL 中的 /dbname）")
        if not (parsed.username or "").strip():
            errors.append("MySQL 连接缺少用户名（DB_USER 或 DATABASE_URL 中的 user）")
        return errors
