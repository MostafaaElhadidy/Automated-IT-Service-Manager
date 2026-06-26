"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "configuration_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("ci_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="operational"),
        sa.Column("criticality", sa.Integer(), nullable=False, server_default="3"),
    )

    op.create_table(
        "ci_relationships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("configuration_items.id"), nullable=False),
        sa.Column("target_id", sa.String(64), sa.ForeignKey("configuration_items.id"), nullable=False),
        sa.Column("rel_type", sa.String(32), nullable=False),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(4), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("affected_ci", sa.String(64), sa.ForeignKey("configuration_items.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "action_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.String(64), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("runbook_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.String(64), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("action_log")
    op.drop_table("tickets")
    op.drop_table("ci_relationships")
    op.drop_table("configuration_items")
