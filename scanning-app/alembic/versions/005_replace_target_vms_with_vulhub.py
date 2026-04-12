"""Replace target_vms table with vulhub_targets for K8s-based vulnerable environments.

Revision ID: 005
Revises: 004
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the Proxmox-based target_vms table (ephemeral data, no historical value)
    op.drop_index("ix_target_vms_ttl", table_name="target_vms")
    op.drop_index("ix_target_vms_status", table_name="target_vms")
    op.drop_table("target_vms")

    # Create the new vulhub_targets table for K8s-based vulnerable environments
    op.create_table(
        "vulhub_targets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("env_id", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("namespace", sa.String, unique=True, nullable=False),
        sa.Column("service_endpoint", sa.String, nullable=False),
        sa.Column("cve_id", sa.String, nullable=True),
        sa.Column("category", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="deploying"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("ttl_expires_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("destroyed_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("ports_json", JSONB, nullable=True),
    )
    op.create_index("ix_vulhub_targets_status", "vulhub_targets", ["status"])
    op.create_index("ix_vulhub_targets_ttl", "vulhub_targets", ["ttl_expires_at"])


def downgrade() -> None:
    # Drop vulhub_targets
    op.drop_index("ix_vulhub_targets_ttl", table_name="vulhub_targets")
    op.drop_index("ix_vulhub_targets_status", table_name="vulhub_targets")
    op.drop_table("vulhub_targets")

    # Recreate target_vms from 004 schema for rollback safety
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
