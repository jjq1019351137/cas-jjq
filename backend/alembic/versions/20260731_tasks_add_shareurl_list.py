"""tasks add shareurl list

Revision ID: 20260731_tasks_add_shareurl_list
Revises: 20260730_audit_logs_v2
Create Date: 2026-07-31 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260731_tasks_add_shareurl_list"
down_revision = "20260730_audit_logs_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("tasks")}
    if "shareurl_list_json" not in columns:
        op.add_column("tasks", sa.Column("shareurl_list_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "shareurl_list_json")
