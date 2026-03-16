"""Database repository — async CRUD operations for all scan-related tables.

All methods accept an ``AsyncSession`` (injected via FastAPI ``Depends``).
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Scan, Host, Service, Vulnerability, IocFinding,
    FaradaySyncLog, AuditLog,
)


# ── Scans ──────────────────────────────────────────────────────────

async def create_scan(session: AsyncSession, **kwargs) -> Scan:
    scan = Scan(**kwargs)
    session.add(scan)
    await session.flush()
    return scan


async def get_scan(session: AsyncSession, scan_id: str) -> Optional[Scan]:
    result = await session.execute(
        select(Scan)
        .where(Scan.id == scan_id)
        .options(
            selectinload(Scan.hosts).selectinload(Host.services),
            selectinload(Scan.hosts).selectinload(Host.vulnerabilities),
            selectinload(Scan.ioc_findings),
        )
    )
    return result.scalar_one_or_none()


async def list_scans(
    session: AsyncSession,
    scan_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Scan]:
    q = select(Scan).order_by(Scan.started_at.desc().nullslast())
    if scan_type:
        q = q.where(Scan.scan_type == scan_type)
    q = q.limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


async def update_scan(session: AsyncSession, scan_id: str, **kwargs) -> None:
    await session.execute(
        update(Scan).where(Scan.id == scan_id).values(**kwargs)
    )


# ── Hosts ──────────────────────────────────────────────────────────

async def upsert_host(
    session: AsyncSession, scan_id: str, ip: str, **kwargs
) -> Host:
    """Get or create a host for the given scan + IP."""
    result = await session.execute(
        select(Host).where(and_(Host.scan_id == scan_id, Host.ip == ip))
    )
    host = result.scalar_one_or_none()
    if host:
        for k, v in kwargs.items():
            setattr(host, k, v)
    else:
        host = Host(scan_id=scan_id, ip=ip, **kwargs)
        session.add(host)
    await session.flush()
    return host


async def list_hosts(
    session: AsyncSession,
    scan_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Host]:
    q = select(Host).options(selectinload(Host.services))
    if scan_id:
        q = q.where(Host.scan_id == scan_id)
    q = q.order_by(Host.ip).limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


async def get_host(session: AsyncSession, host_id: int) -> Optional[Host]:
    result = await session.execute(
        select(Host)
        .where(Host.id == host_id)
        .options(
            selectinload(Host.services),
            selectinload(Host.vulnerabilities),
        )
    )
    return result.scalar_one_or_none()


# ── Services ───────────────────────────────────────────────────────

async def create_service(session: AsyncSession, **kwargs) -> Service:
    svc = Service(**kwargs)
    session.add(svc)
    await session.flush()
    return svc


# ── Vulnerabilities ────────────────────────────────────────────────

async def create_vulnerability(session: AsyncSession, **kwargs) -> Vulnerability:
    vuln = Vulnerability(**kwargs)
    session.add(vuln)
    await session.flush()
    return vuln


async def list_vulns(
    session: AsyncSession,
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    remediation_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Vulnerability]:
    q = select(Vulnerability)
    if scan_id:
        q = q.where(Vulnerability.scan_id == scan_id)
    if severity:
        q = q.where(Vulnerability.severity == severity)
    if remediation_status:
        q = q.where(Vulnerability.remediation_status == remediation_status)
    q = q.order_by(Vulnerability.id).limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


async def update_remediation(
    session: AsyncSession,
    vuln_id: int,
    status: str,
    notes: Optional[str] = None,
) -> None:
    await session.execute(
        update(Vulnerability)
        .where(Vulnerability.id == vuln_id)
        .values(
            remediation_status=status,
            remediation_notes=notes,
            remediation_updated_at=datetime.utcnow(),
        )
    )


async def bulk_update_remediation(
    session: AsyncSession,
    vuln_ids: List[int],
    status: str,
    notes: Optional[str] = None,
) -> int:
    result = await session.execute(
        update(Vulnerability)
        .where(Vulnerability.id.in_(vuln_ids))
        .values(
            remediation_status=status,
            remediation_notes=notes,
            remediation_updated_at=datetime.utcnow(),
        )
    )
    return result.rowcount


# ── IOC Findings ───────────────────────────────────────────────────

async def create_ioc_finding(session: AsyncSession, **kwargs) -> IocFinding:
    finding = IocFinding(**kwargs)
    session.add(finding)
    await session.flush()
    return finding


async def list_ioc_findings(
    session: AsyncSession,
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[IocFinding]:
    q = select(IocFinding)
    if scan_id:
        q = q.where(IocFinding.scan_id == scan_id)
    if severity:
        q = q.where(IocFinding.severity == severity)
    q = q.order_by(IocFinding.id).limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


# ── Faraday Sync Log ──────────────────────────────────────────────

async def create_sync_log(session: AsyncSession, **kwargs) -> FaradaySyncLog:
    log = FaradaySyncLog(**kwargs)
    session.add(log)
    await session.flush()
    return log


async def get_pending_retries(session: AsyncSession) -> List[FaradaySyncLog]:
    """Get sync logs that need retry (failed, not exhausted, due now)."""
    result = await session.execute(
        select(FaradaySyncLog)
        .where(
            and_(
                FaradaySyncLog.success == False,  # noqa: E712
                FaradaySyncLog.next_retry_at != None,  # noqa: E711
                FaradaySyncLog.next_retry_at <= func.now(),
                FaradaySyncLog.retry_count < 3,
            )
        )
        .order_by(FaradaySyncLog.next_retry_at)
    )
    return list(result.scalars().all())


# ── Audit Log ─────────────────────────────────────────────────────

async def create_audit_entry(session: AsyncSession, **kwargs) -> AuditLog:
    entry = AuditLog(**kwargs)
    session.add(entry)
    await session.flush()
    return entry


async def list_audit_log(
    session: AsyncSession,
    action: Optional[str] = None,
    user: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[AuditLog]:
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action == action)
    if user:
        q = q.where(AuditLog.user == user)
    q = q.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


# ── Summary / Aggregations ────────────────────────────────────────

async def get_summary(session: AsyncSession) -> dict:
    """Dashboard summary: total hosts, vulns by severity, scan count."""
    scan_count = await session.scalar(select(func.count(Scan.id)))
    host_count = await session.scalar(select(func.count(func.distinct(Host.ip))))

    severity_q = await session.execute(
        select(Vulnerability.severity, func.count(Vulnerability.id))
        .group_by(Vulnerability.severity)
    )
    severity_counts = {row[0]: row[1] for row in severity_q.all()}

    return {
        "scan_count": scan_count or 0,
        "host_count": host_count or 0,
        "vuln_total": sum(severity_counts.values()),
        "vulns_by_severity": severity_counts,
    }


async def get_scan_comparison(
    session: AsyncSession, scan_a_id: str, scan_b_id: str
) -> dict:
    """Compare two scans: new/resolved/common hosts and vulns."""
    hosts_a = set()
    hosts_b = set()
    vulns_a = set()
    vulns_b = set()

    for row in (await session.execute(
        select(Host.ip).where(Host.scan_id == scan_a_id)
    )).scalars():
        hosts_a.add(row)

    for row in (await session.execute(
        select(Host.ip).where(Host.scan_id == scan_b_id)
    )).scalars():
        hosts_b.add(row)

    for row in (await session.execute(
        select(Vulnerability.name, Vulnerability.severity)
        .where(Vulnerability.scan_id == scan_a_id)
    )).all():
        vulns_a.add((row[0], row[1]))

    for row in (await session.execute(
        select(Vulnerability.name, Vulnerability.severity)
        .where(Vulnerability.scan_id == scan_b_id)
    )).all():
        vulns_b.add((row[0], row[1]))

    return {
        "hosts": {
            "new": sorted(hosts_b - hosts_a),
            "resolved": sorted(hosts_a - hosts_b),
            "common": sorted(hosts_a & hosts_b),
        },
        "vulns": {
            "new": sorted([{"name": v[0], "severity": v[1]} for v in vulns_b - vulns_a], key=lambda x: x["name"]),
            "resolved": sorted([{"name": v[0], "severity": v[1]} for v in vulns_a - vulns_b], key=lambda x: x["name"]),
            "common_count": len(vulns_a & vulns_b),
        },
    }
