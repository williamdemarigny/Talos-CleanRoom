"""SQLAlchemy ORM models for the scanning console database.

These models mirror the schema defined in docs/vuln-management-plan.md Section 2.2.
Alembic migrations in alembic/versions/ keep the database in sync.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Integer, String, Text, Boolean, ForeignKey, Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Scan(Base):
    __tablename__ = "scans"

    id = Column(String, primary_key=True)  # uuid[:8]
    scan_type = Column(String, nullable=False)  # "security" | "ioc"
    target = Column(Text, nullable=False)
    profile = Column(String, nullable=True)  # quick/standard/thorough/custom, NULL for IOC
    mount_type = Column(String, nullable=True)  # ssh/smb, NULL for security
    scan_path = Column(Text, nullable=True)  # IOC only
    status = Column(String, nullable=False, default="idle")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    tools_json = Column(JSONB, nullable=True)  # tool states array
    custom_modules = Column(JSONB, nullable=True)
    openvas_config = Column(String, nullable=True)
    openvas_families = Column(JSONB, nullable=True)

    hosts = relationship("Host", back_populates="scan", cascade="all, delete-orphan")
    vulnerabilities = relationship("Vulnerability", back_populates="scan", cascade="all, delete-orphan")
    ioc_findings = relationship("IocFinding", back_populates="scan", cascade="all, delete-orphan")
    faraday_sync_logs = relationship("FaradaySyncLog", back_populates="scan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_scans_started_at", "started_at"),
        Index("ix_scans_status", "status"),
        Index("ix_scans_scan_type", "scan_type"),
    )


class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    ip = Column(Text, nullable=False)
    os = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    hostnames = Column(JSONB, nullable=True)
    tags = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=func.now())

    scan = relationship("Scan", back_populates="hosts")
    services = relationship("Service", back_populates="host", cascade="all, delete-orphan")
    vulnerabilities = relationship("Vulnerability", back_populates="host", cascade="all, delete-orphan")
    ioc_findings = relationship("IocFinding", back_populates="host")

    __table_args__ = (
        Index("ix_hosts_ip", "ip"),
        Index("ix_hosts_scan_id", "scan_id"),
        Index("uq_hosts_scan_ip", "scan_id", "ip", unique=True),
    )


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=True)
    port = Column(Integer, nullable=False)
    protocol = Column(String, default="tcp")
    status = Column(String, default="open")
    version = Column(Text, nullable=True)

    host = relationship("Host", back_populates="services")

    __table_args__ = (
        Index("ix_services_host_id", "host_id"),
        Index("ix_services_port", "port"),
    )


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String, nullable=False)  # critical/high/medium/low/info/unclassified
    refs = Column(JSONB, nullable=True)  # reference URLs
    resolution = Column(Text, nullable=True)
    data = Column(Text, nullable=True)
    external_id = Column(String, nullable=True)  # CVE
    tags = Column(JSONB, nullable=True)
    type = Column(String, default="Vulnerability")
    tool_source = Column(String, nullable=True)  # nmap/openvas/metasploit
    # Web vuln fields
    path = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
    method = Column(String, nullable=True)
    request = Column(Text, nullable=True)
    response = Column(Text, nullable=True)
    query = Column(Text, nullable=True)
    # Remediation tracking
    remediation_status = Column(String, default="open")
    remediation_notes = Column(Text, nullable=True)
    remediation_updated_at = Column(DateTime, nullable=True)

    scan = relationship("Scan", back_populates="vulnerabilities")
    host = relationship("Host", back_populates="vulnerabilities")

    __table_args__ = (
        Index("ix_vulns_severity", "severity"),
        Index("ix_vulns_scan_id", "scan_id"),
        Index("ix_vulns_host_id", "host_id"),
        Index("ix_vulns_remediation_status", "remediation_status"),
        Index("ix_vulns_external_id", "external_id"),
    )


class IocFinding(Base):
    __tablename__ = "ioc_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True)
    severity = Column(String, nullable=False)  # alert/warning/notice
    score = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=False)
    rule_name = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    matched_strings = Column(JSONB, nullable=True)
    hash_md5 = Column(String, nullable=True)
    hash_sha256 = Column(String, nullable=True)
    tags = Column(JSONB, nullable=True)
    remediation_status = Column(String, default="open")
    remediation_notes = Column(Text, nullable=True)
    remediation_updated_at = Column(DateTime, nullable=True)

    scan = relationship("Scan", back_populates="ioc_findings")
    host = relationship("Host", back_populates="ioc_findings")

    __table_args__ = (
        Index("ix_ioc_scan_id", "scan_id"),
        Index("ix_ioc_severity", "severity"),
        Index("ix_ioc_hash_sha256", "hash_sha256"),
    )


class FaradaySyncLog(Base):
    __tablename__ = "faraday_sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    synced_at = Column(DateTime, nullable=True)
    success = Column(Boolean, nullable=True)
    detail = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    scan_type = Column(String, nullable=True)  # "security" | "ioc"

    scan = relationship("Scan", back_populates="faraday_sync_logs")

    __table_args__ = (
        Index("ix_faraday_sync_success_retry", "success", "next_retry_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=func.now())
    action = Column(Text, nullable=False)
    user = Column(Text, nullable=True)
    source_ip = Column(Text, nullable=True)
    resource_type = Column(Text, nullable=True)
    resource_id = Column(Text, nullable=True)
    detail = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_user", "user"),
    )
