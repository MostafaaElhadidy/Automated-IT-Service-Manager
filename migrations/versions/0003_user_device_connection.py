"""User device connection attributes (MeshCentral remote remediation)

Adds the columns SynapseITSM needs to reach each user's own PC/laptop and
apply runbook fixes remotely via MeshCentral. Populated by
meshcentral_client.sync_devices() once the MeshAgent enrolls on the device.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("meshcentral_nodeid", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("device_hostname", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("last_known_ip", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("os_platform", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column("agent_online", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("device_last_seen", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_meshcentral_nodeid", "users", ["meshcentral_nodeid"])


def downgrade() -> None:
    op.drop_index("ix_users_meshcentral_nodeid", table_name="users")
    op.drop_column("users", "device_last_seen")
    op.drop_column("users", "agent_online")
    op.drop_column("users", "os_platform")
    op.drop_column("users", "last_known_ip")
    op.drop_column("users", "device_hostname")
    op.drop_column("users", "meshcentral_nodeid")
