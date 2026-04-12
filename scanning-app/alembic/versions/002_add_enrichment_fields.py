"""Add vulnerability enrichment columns (CVSS, EPSS, CPE, threat intel).

Revision ID: 002
Revises: 001
Create Date: 2026-03-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CVSS fields
    op.add_column("vulnerabilities", sa.Column("cvss_score", sa.Float, nullable=True))
    op.add_column("vulnerabilities", sa.Column("cvss_vector", sa.String, nullable=True))
    op.add_column("vulnerabilities", sa.Column("cvss_version", sa.String, nullable=True))
    op.add_column("vulnerabilities", sa.Column("nvd_severity", sa.String, nullable=True))

    # EPSS fields
    op.add_column("vulnerabilities", sa.Column("epss_score", sa.Float, nullable=True))
    op.add_column("vulnerabilities", sa.Column("epss_percentile", sa.Float, nullable=True))

    # CPE / weakness fields
    op.add_column("vulnerabilities", sa.Column("cpe_matches", JSONB, nullable=True))
    op.add_column("vulnerabilities", sa.Column("weakness_ids", JSONB, nullable=True))

    # Threat intelligence
    op.add_column("vulnerabilities", sa.Column("threat_intel", JSONB, nullable=True))

    # Enrichment metadata
    op.add_column("vulnerabilities", sa.Column(
        "enrichment_status", sa.String, nullable=False, server_default="skipped",
    ))
    op.add_column("vulnerabilities", sa.Column("enrichment_source", sa.String, nullable=True))
    op.add_column("vulnerabilities", sa.Column("enriched_at", sa.DateTime, nullable=True))

    # Indexes for filtering/sorting
    op.create_index("ix_vulns_cvss_score", "vulnerabilities", ["cvss_score"])
    op.create_index("ix_vulns_epss_score", "vulnerabilities", ["epss_score"])
    op.create_index("ix_vulns_enrichment_status", "vulnerabilities", ["enrichment_status"])


def downgrade() -> None:
    op.drop_index("ix_vulns_enrichment_status")
    op.drop_index("ix_vulns_epss_score")
    op.drop_index("ix_vulns_cvss_score")

    op.drop_column("vulnerabilities", "enriched_at")
    op.drop_column("vulnerabilities", "enrichment_source")
    op.drop_column("vulnerabilities", "enrichment_status")
    op.drop_column("vulnerabilities", "threat_intel")
    op.drop_column("vulnerabilities", "weakness_ids")
    op.drop_column("vulnerabilities", "cpe_matches")
    op.drop_column("vulnerabilities", "epss_percentile")
    op.drop_column("vulnerabilities", "epss_score")
    op.drop_column("vulnerabilities", "nvd_severity")
    op.drop_column("vulnerabilities", "cvss_version")
    op.drop_column("vulnerabilities", "cvss_vector")
    op.drop_column("vulnerabilities", "cvss_score")
