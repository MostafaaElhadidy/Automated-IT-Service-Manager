"""Users table + ticket ownership (RBAC)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="end_user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.add_column(
        "tickets",
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_tickets_owner_id", "tickets", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_owner_id", table_name="tickets")
    op.drop_column("tickets", "owner_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
