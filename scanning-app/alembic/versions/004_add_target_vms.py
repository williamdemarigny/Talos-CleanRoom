"""Add target_vms table for Target Lab VM lifecycle tracking.

Revision ID: 004
Revises: 003
Create Date: 2026-03-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "target_vms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vmid", sa.Integer, unique=True, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("template_type", sa.String, nullable=False),
        sa.Column("ip_address", sa.String, nullable=False),
        sa.Column("proxmox_node", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="deploying"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("ttl_expires_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("destroyed_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_target_vms_status", "target_vms", ["status"])
    op.create_index("ix_target_vms_ttl", "target_vms", ["ttl_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_target_vms_ttl", table_name="target_vms")
    op.drop_index("ix_target_vms_status", table_name="target_vms")
    op.drop_table("target_vms")
