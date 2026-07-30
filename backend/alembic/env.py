from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.core.settings import settings
from app.db.base import Base
from app.db.runtime import build_runtime
import app.models as _models


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return settings.database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _ensure_wide_version_table(connection) -> None:
    if connection.dialect.name != "mysql":
        return
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "version_num VARCHAR(255) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    connection.exec_driver_sql(
        "ALTER TABLE alembic_version MODIFY version_num VARCHAR(255) NOT NULL"
    )
    connection.commit()


def run_migrations_online() -> None:
    runtime = build_runtime(for_migrations=True)
    connectable = runtime.engine

    with connectable.connect() as connection:
        _ensure_wide_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
