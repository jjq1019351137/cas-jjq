"""audit logs v2: drop and rebuild with readable business audit fields

Revision ID: 20260730_audit_logs_v2
Revises: 20260723_sync_task_drama_links_sort_order
Create Date: 2026-07-30 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import MEDIUMTEXT


revision = "20260730_audit_logs_v2"
down_revision = "20260723_sync_task_drama_links_sort_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_logs" in inspector.get_table_names():
        # 直接 drop 表（索引与外键一并删除）；MySQL 下单独 drop 索引会因外键依赖报 1553
        op.drop_table("audit_logs")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("actor_type", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("detail", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_source"), "audit_logs", ["source"], unique=False)
    op.create_index(op.f("ix_audit_logs_category"), "audit_logs", ["category"], unique=False)
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_success"), "audit_logs", ["success"], unique=False)
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_logs" in inspector.get_table_names():
        op.drop_table("audit_logs")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("success", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("detail", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
