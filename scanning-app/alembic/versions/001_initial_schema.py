"""Initial schema for scanning console database.

Revision ID: 001
Revises:
Create Date: 2026-03-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- scans --
    op.create_table(
        "scans",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("scan_type", sa.String, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("profile", sa.String, nullable=True),
        sa.Column("mount_type", sa.String, nullable=True),
        sa.Column("scan_path", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="idle"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("tools_json", JSONB, nullable=True),
        sa.Column("custom_modules", JSONB, nullable=True),
        sa.Column("openvas_config", sa.String, nullable=True),
        sa.Column("openvas_families", JSONB, nullable=True),
    )
    op.create_index("ix_scans_started_at", "scans", ["started_at"])
    op.create_index("ix_scans_status", "scans", ["status"])
    op.create_index("ix_scans_scan_type", "scans", ["scan_type"])

    # -- hosts --
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.String, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip", sa.Text, nullable=False),
        sa.Column("os", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("hostnames", JSONB, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_hosts_ip", "hosts", ["ip"])
    op.create_index("ix_hosts_scan_id", "hosts", ["scan_id"])
    op.create_index("uq_hosts_scan_ip", "hosts", ["scan_id", "ip"], unique=True)

    # -- services --
    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("host_id", sa.Integer, sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_id", sa.String, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("protocol", sa.String, server_default="tcp"),
        sa.Column("status", sa.String, server_default="open"),
        sa.Column("version", sa.Text, nullable=True),
    )
    op.create_index("ix_services_host_id", "services", ["host_id"])
    op.create_index("ix_services_port", "services", ["port"])

    # -- vulnerabilities --
    op.create_table(
        "vulnerabilities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.String, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer, sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("refs", JSONB, nullable=True),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("data", sa.Text, nullable=True),
        sa.Column("external_id", sa.String, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("type", sa.String, server_default="Vulnerability"),
        sa.Column("tool_source", sa.String, nullable=True),
        sa.Column("path", sa.Text, nullable=True),
        sa.Column("website", sa.Text, nullable=True),
        sa.Column("method", sa.String, nullable=True),
        sa.Column("request", sa.Text, nullable=True),
        sa.Column("response", sa.Text, nullable=True),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("remediation_status", sa.String, server_default="open"),
        sa.Column("remediation_notes", sa.Text, nullable=True),
        sa.Column("remediation_updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_vulns_severity", "vulnerabilities", ["severity"])
    op.create_index("ix_vulns_scan_id", "vulnerabilities", ["scan_id"])
    op.create_index("ix_vulns_host_id", "vulnerabilities", ["host_id"])
    op.create_index("ix_vulns_remediation_status", "vulnerabilities", ["remediation_status"])
    op.create_index("ix_vulns_external_id", "vulnerabilities", ["external_id"])

    # -- ioc_findings --
    op.create_table(
        "ioc_findings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.String, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer, sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("rule_name", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("matched_strings", JSONB, nullable=True),
        sa.Column("hash_md5", sa.String, nullable=True),
        sa.Column("hash_sha256", sa.String, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("remediation_status", sa.String, server_default="open"),
        sa.Column("remediation_notes", sa.Text, nullable=True),
        sa.Column("remediation_updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_ioc_scan_id", "ioc_findings", ["scan_id"])
    op.create_index("ix_ioc_severity", "ioc_findings", ["severity"])
    op.create_index("ix_ioc_hash_sha256", "ioc_findings", ["hash_sha256"])

    # -- faraday_sync_log --
    op.create_table(
        "faraday_sync_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.String, sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("synced_at", sa.DateTime, nullable=True),
        sa.Column("success", sa.Boolean, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime, nullable=True),
        sa.Column("scan_type", sa.String, nullable=True),
    )
    op.create_index("ix_faraday_sync_success_retry", "faraday_sync_log", ["success", "next_retry_at"])

    # -- audit_log --
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now()),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("user", sa.Text, nullable=True),
        sa.Column("source_ip", sa.Text, nullable=True),
        sa.Column("resource_type", sa.Text, nullable=True),
        sa.Column("resource_id", sa.Text, nullable=True),
        sa.Column("detail", JSONB, nullable=True),
    )
    op.create_index("ix_audit_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_action", "audit_log", ["action"])
    op.create_index("ix_audit_user", "audit_log", ["user"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("faraday_sync_log")
    op.drop_table("ioc_findings")
    op.drop_table("vulnerabilities")
    op.drop_table("services")
    op.drop_table("hosts")
    op.drop_table("scans")
