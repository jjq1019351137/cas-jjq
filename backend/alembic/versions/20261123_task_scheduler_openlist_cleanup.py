"""task_scheduler_settings add openlist cleanup fields

Revision ID: 20261123_task_scheduler_openlist_cleanup
Revises: 20260731_tasks_add_shareurl_list
Create Date: 2026-11-23 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261123_task_scheduler_openlist_cleanup"
down_revision = "20260731_tasks_add_shareurl_list"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_scheduler_settings" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("task_scheduler_settings")}
    if "openlist_cleanup_enabled" not in columns:
        op.add_column(
            "task_scheduler_settings",
            sa.Column("openlist_cleanup_enabled", sa.Boolean(), nullable=False, server_default="0"),
        )
    if "openlist_cleanup_path" not in columns:
        op.add_column(
            "task_scheduler_settings",
            sa.Column("openlist_cleanup_path", sa.String(length=512), nullable=False, server_default=""),
        )
    if "openlist_cleanup_crontab" not in columns:
        op.add_column(
            "task_scheduler_settings",
            sa.Column("openlist_cleanup_crontab", sa.String(length=64), nullable=False, server_default="0 3 * * *"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_scheduler_settings" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("task_scheduler_settings")}
    for name in ("openlist_cleanup_crontab", "openlist_cleanup_path", "openlist_cleanup_enabled"):
        if name in columns:
            op.drop_column("task_scheduler_settings", name)
