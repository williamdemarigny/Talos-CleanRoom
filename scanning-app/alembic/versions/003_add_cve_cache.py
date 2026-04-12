"""Add CVE cache table for cross-scan enrichment deduplication.

Revision ID: 003
Revises: 002
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cve_cache",
        sa.Column("cve_id", sa.String, primary_key=True),
        sa.Column("cvss_score", sa.Float, nullable=True),
        sa.Column("cvss_vector", sa.String, nullable=True),
        sa.Column("cvss_version", sa.String, nullable=True),
        sa.Column("nvd_severity", sa.String, nullable=True),
        sa.Column("weakness_ids", JSONB, nullable=True),
        sa.Column("cpe_matches", JSONB, nullable=True),
        sa.Column("epss_score", sa.Float, nullable=True),
        sa.Column("epss_percentile", sa.Float, nullable=True),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_cve_cache_expires", "cve_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_cve_cache_expires")
    op.drop_table("cve_cache")
