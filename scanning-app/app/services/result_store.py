"""Result store — dual-write layer that persists scan results to PostgreSQL.

This module provides functions that the scan and IOC scan services call
after completing each phase to persist results to the database.  Faraday
uploads remain the secondary (best-effort) path; PostgreSQL is the
primary, synchronous store.

All functions accept an ``AsyncSession`` obtained from ``get_session()``.

Batch variants (``persist_hosts_batch``, ``persist_vulns_batch``,
``persist_ioc_findings_batch``) commit once for many rows, reducing
database round-trips from O(N) to O(1).
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository as repo
from app.db.models import Scan, Host, Service, Vulnerability, IocFinding

logger = logging.getLogger(__name__)


async def persist_scan_start(
    session: AsyncSession,
    scan_id: str,
    scan_type: str,
    target: str,
    profile: Optional[str] = None,
    mount_type: Optional[str] = None,
    scan_path: Optional[str] = None,
    tools_json: Optional[list] = None,
    custom_modules: Optional[list] = None,
    openvas_config: Optional[str] = None,
    openvas_families: Optional[list] = None,
) -> Scan:
    """Create a scan row when a scan starts."""
    scan = await repo.create_scan(
        session,
        id=scan_id,
        scan_type=scan_type,
        target=target,
        profile=profile,
        mount_type=mount_type,
        scan_path=scan_path,
        status="running",
        started_at=datetime.utcnow(),
        tools_json=tools_json,
        custom_modules=custom_modules,
        openvas_config=openvas_config,
        openvas_families=openvas_families,
    )
    await session.commit()
    return scan


async def persist_scan_complete(
    session: AsyncSession,
    scan_id: str,
    status: str,
    error_message: Optional[str] = None,
    tools_json: Optional[list] = None,
) -> None:
    """Update scan row when a scan finishes."""
    kwargs = {
        "status": status,
        "completed_at": datetime.utcnow(),
    }
    if error_message is not None:
        kwargs["error_message"] = error_message
    if tools_json is not None:
        kwargs["tools_json"] = tools_json
    await repo.update_scan(session, scan_id, **kwargs)
    await session.commit()


async def persist_host(
    session: AsyncSession,
    scan_id: str,
    ip: str,
    os: Optional[str] = None,
    hostnames: Optional[list] = None,
    description: Optional[str] = None,
) -> int:
    """Upsert a host and return its database ID."""
    host = await repo.upsert_host(
        session, scan_id, ip,
        os=os, hostnames=hostnames, description=description,
    )
    await session.commit()
    return host.id


async def persist_service(
    session: AsyncSession,
    host_id: int,
    scan_id: str,
    port: int,
    protocol: str = "tcp",
    name: Optional[str] = None,
    version: Optional[str] = None,
    status: str = "open",
) -> int:
    """Create a service row and return its ID."""
    svc = await repo.create_service(
        session,
        host_id=host_id,
        scan_id=scan_id,
        port=port,
        protocol=protocol,
        name=name,
        version=version,
        status=status,
    )
    await session.commit()
    return svc.id


async def persist_vulnerability(
    session: AsyncSession,
    scan_id: str,
    host_id: int,
    name: str,
    severity: str,
    service_id: Optional[int] = None,
    description: Optional[str] = None,
    refs: Optional[list] = None,
    resolution: Optional[str] = None,
    data: Optional[str] = None,
    external_id: Optional[str] = None,
    tags: Optional[list] = None,
    tool_source: Optional[str] = None,
    **extra,
) -> int:
    """Create a vulnerability row and return its ID."""
    # Set enrichment_status='pending' for CVE-bearing vulns so the
    # enrichment service picks them up after scan completion.
    if external_id and external_id.startswith("CVE-"):
        extra.setdefault("enrichment_status", "pending")
    vuln = await repo.create_vulnerability(
        session,
        scan_id=scan_id,
        host_id=host_id,
        service_id=service_id,
        name=name,
        severity=severity,
        description=description,
        refs=refs,
        resolution=resolution,
        data=data,
        external_id=external_id,
        tags=tags,
        tool_source=tool_source,
        **extra,
    )
    await session.commit()
    return vuln.id


async def persist_ioc_finding(
    session: AsyncSession,
    scan_id: str,
    severity: str,
    score: int,
    file_path: str,
    host_id: Optional[int] = None,
    rule_name: Optional[str] = None,
    description: Optional[str] = None,
    matched_strings: Optional[list] = None,
    hash_md5: Optional[str] = None,
    hash_sha256: Optional[str] = None,
    tags: Optional[list] = None,
) -> int:
    """Create an IOC finding row and return its ID."""
    finding = await repo.create_ioc_finding(
        session,
        scan_id=scan_id,
        host_id=host_id,
        severity=severity,
        score=score,
        file_path=file_path,
        rule_name=rule_name,
        description=description,
        matched_strings=matched_strings,
        hash_md5=hash_md5,
        hash_sha256=hash_sha256,
        tags=tags,
    )
    await session.commit()
    return finding.id


async def persist_faraday_sync(
    session: AsyncSession,
    scan_id: str,
    success: bool,
    scan_type: str = "security",
    detail: Optional[str] = None,
) -> None:
    """Log a Faraday sync attempt."""
    await repo.create_sync_log(
        session,
        scan_id=scan_id,
        synced_at=datetime.utcnow(),
        success=success,
        detail=detail,
        scan_type=scan_type,
    )
    await session.commit()


async def persist_audit(
    session: AsyncSession,
    action: str,
    user: Optional[str] = None,
    source_ip: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """Create an audit log entry."""
    await repo.create_audit_entry(
        session,
        action=action,
        user=user,
        source_ip=source_ip,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
    )
    await session.commit()


# ── Batch Operations ─────────────────────────────────────────────
# These functions reduce database round-trips from O(N) to O(1) by
# batching multiple rows into a single commit.


async def persist_hosts_batch(
    session: AsyncSession,
    scan_id: str,
    hosts: List[Dict],
) -> Dict[str, int]:
    """Persist multiple hosts in a single transaction.

    Args:
        session: Async database session.
        scan_id: Parent scan ID.
        hosts: List of dicts with keys: ip, os, hostnames, description.

    Returns:
        Mapping of IP address to database host ID.
    """
    ip_to_id: Dict[str, int] = {}
    for h in hosts:
        host = await repo.upsert_host(
            session, scan_id, h["ip"],
            os=h.get("os"),
            hostnames=h.get("hostnames"),
            description=h.get("description"),
        )
        ip_to_id[h["ip"]] = host.id
    await session.commit()
    return ip_to_id


async def persist_services_batch(
    session: AsyncSession,
    scan_id: str,
    services: List[Dict],
) -> Dict[Tuple[int, int, str], int]:
    """Persist multiple services in a single transaction.

    Args:
        session: Async database session.
        scan_id: Parent scan ID.
        services: List of dicts with keys: host_id, port, protocol, name, version, status.

    Returns:
        Mapping of (host_id, port, protocol) to database service ID.
    """
    svc_to_id: Dict[Tuple[int, int, str], int] = {}
    for s in services:
        svc = await repo.create_service(
            session,
            host_id=s["host_id"],
            scan_id=scan_id,
            port=s["port"],
            protocol=s.get("protocol", "tcp"),
            name=s.get("name"),
            version=s.get("version"),
            status=s.get("status", "open"),
        )
        svc_to_id[(s["host_id"], s["port"], s.get("protocol", "tcp"))] = svc.id
    await session.commit()
    return svc_to_id


async def persist_vulns_batch(
    session: AsyncSession,
    scan_id: str,
    vulns: List[Dict],
) -> int:
    """Persist multiple vulnerabilities in a single transaction.

    Args:
        session: Async database session.
        scan_id: Parent scan ID.
        vulns: List of dicts matching persist_vulnerability kwargs.

    Returns:
        Number of vulnerabilities persisted.
    """
    for v in vulns:
        extra = {}
        ext_id = v.get("external_id")
        if ext_id and ext_id.startswith("CVE-"):
            extra["enrichment_status"] = v.get("enrichment_status", "pending")
        await repo.create_vulnerability(
            session,
            scan_id=scan_id,
            host_id=v["host_id"],
            service_id=v.get("service_id"),
            name=v["name"],
            severity=v["severity"],
            description=v.get("description"),
            refs=v.get("refs"),
            resolution=v.get("resolution"),
            data=v.get("data"),
            external_id=ext_id,
            tags=v.get("tags"),
            tool_source=v.get("tool_source"),
            **extra,
        )
    await session.commit()
    return len(vulns)


async def persist_ioc_findings_batch(
    session: AsyncSession,
    scan_id: str,
    findings: List[Dict],
    host_id: Optional[int] = None,
) -> int:
    """Persist multiple IOC findings in a single transaction.

    Args:
        session: Async database session.
        scan_id: Parent scan ID.
        findings: List of dicts matching persist_ioc_finding kwargs.
        host_id: Optional host ID to assign to all findings.

    Returns:
        Number of findings persisted.
    """
    for f in findings:
        await repo.create_ioc_finding(
            session,
            scan_id=scan_id,
            host_id=f.get("host_id", host_id),
            severity=f["severity"],
            score=f["score"],
            file_path=f["file_path"],
            rule_name=f.get("rule_name"),
            description=f.get("description"),
            matched_strings=f.get("matched_strings"),
            hash_md5=f.get("hash_md5"),
            hash_sha256=f.get("hash_sha256"),
            tags=f.get("tags"),
        )
    await session.commit()
    return len(findings)
