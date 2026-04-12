"""Reports API router — read-only endpoints for scan results, hosts, vulns, and audit log."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from talos_common.auth import get_current_user
from app.db.engine import get_session
from app.db import repository as repo

router = APIRouter()

_VALID_REMEDIATION_STATUSES = {"open", "in_progress", "resolved", "accepted", "false_positive"}


@router.get("/summary")
async def get_summary(
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Dashboard summary: total hosts, vulns by severity, scan count."""
    return await repo.get_summary(session)


@router.get("/scans")
async def list_scans(
    scan_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List all scans, optionally filtered by type."""
    scans = await repo.list_scans(session, scan_type=scan_type, limit=limit, offset=offset)
    return {"scans": [
        {
            "id": s.id,
            "scan_type": s.scan_type,
            "target": s.target,
            "profile": s.profile,
            "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "error_message": s.error_message,
        }
        for s in scans
    ]}


@router.get("/scans/{scan_id}")
async def get_scan_detail(
    scan_id: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get full scan detail with hosts, services, vulns, and IOC findings."""
    scan = await repo.get_scan(session, scan_id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    return {
        "id": scan.id,
        "scan_type": scan.scan_type,
        "target": scan.target,
        "profile": scan.profile,
        "mount_type": scan.mount_type,
        "scan_path": scan.scan_path,
        "status": scan.status,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "error_message": scan.error_message,
        "tools_json": scan.tools_json,
        "lab_env_id": scan.lab_env_id,
        "hosts": [
            {
                "id": h.id,
                "ip": h.ip,
                "os": h.os,
                "hostnames": h.hostnames,
                "services": [
                    {
                        "id": svc.id,
                        "port": svc.port,
                        "protocol": svc.protocol,
                        "name": svc.name,
                        "version": svc.version,
                        "status": svc.status,
                    }
                    for svc in h.services
                ],
                "vulnerabilities": [
                    {
                        "id": v.id,
                        "name": v.name,
                        "severity": v.severity,
                        "description": v.description,
                        "external_id": v.external_id,
                        "tool_source": v.tool_source,
                        "remediation_status": v.remediation_status,
                        "remediation_notes": v.remediation_notes,
                        "cvss_score": v.cvss_score,
                        "cvss_vector": v.cvss_vector,
                        "cvss_version": v.cvss_version,
                        "nvd_severity": v.nvd_severity,
                        "epss_score": v.epss_score,
                        "epss_percentile": v.epss_percentile,
                        "enrichment_status": v.enrichment_status,
                        "refs": v.refs,
                        "weakness_ids": v.weakness_ids,
                        "threat_intel": v.threat_intel,
                    }
                    for v in h.vulnerabilities
                ],
            }
            for h in scan.hosts
        ],
        "ioc_findings": [
            {
                "id": f.id,
                "severity": f.severity,
                "score": f.score,
                "file_path": f.file_path,
                "rule_name": f.rule_name,
                "description": f.description,
                "hash_sha256": f.hash_sha256,
                "remediation_status": f.remediation_status,
            }
            for f in scan.ioc_findings
        ],
    }


@router.get("/hosts")
async def list_hosts(
    scan_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List hosts, optionally filtered by scan."""
    hosts = await repo.list_hosts(session, scan_id=scan_id, limit=limit, offset=offset)
    return {"hosts": [
        {
            "id": h.id,
            "scan_id": h.scan_id,
            "ip": h.ip,
            "os": h.os,
            "hostnames": h.hostnames,
            "services_count": len(h.services),
        }
        for h in hosts
    ]}


@router.get("/hosts/{host_id}")
async def get_host_detail(
    host_id: int,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get host detail with services and vulnerabilities."""
    host = await repo.get_host(session, host_id)
    if not host:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")

    return {
        "id": host.id,
        "scan_id": host.scan_id,
        "ip": host.ip,
        "os": host.os,
        "hostnames": host.hostnames,
        "services": [
            {
                "id": svc.id,
                "port": svc.port,
                "protocol": svc.protocol,
                "name": svc.name,
                "version": svc.version,
                "status": svc.status,
            }
            for svc in host.services
        ],
        "vulnerabilities": [
            {
                "id": v.id,
                "name": v.name,
                "severity": v.severity,
                "description": v.description,
                "external_id": v.external_id,
                "tool_source": v.tool_source,
                "remediation_status": v.remediation_status,
                "remediation_notes": v.remediation_notes,
                "cvss_score": v.cvss_score,
                "cvss_vector": v.cvss_vector,
                "cvss_version": v.cvss_version,
                "nvd_severity": v.nvd_severity,
                "epss_score": v.epss_score,
                "epss_percentile": v.epss_percentile,
                "enrichment_status": v.enrichment_status,
                "refs": v.refs,
                "weakness_ids": v.weakness_ids,
                "threat_intel": v.threat_intel,
            }
            for v in host.vulnerabilities
        ],
    }


@router.get("/vulns")
async def list_vulns(
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    remediation_status: Optional[str] = None,
    enrichment_status: Optional[str] = None,
    cvss_min: Optional[float] = None,
    epss_min: Optional[float] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List vulnerabilities with optional filters and sorting."""
    vulns = await repo.list_vulns(
        session, scan_id=scan_id, severity=severity,
        remediation_status=remediation_status,
        enrichment_status=enrichment_status,
        cvss_min=cvss_min, epss_min=epss_min,
        sort_by=sort_by, sort_order=sort_order,
        limit=limit, offset=offset,
    )
    return {"vulns": [
        {
            "id": v.id,
            "scan_id": v.scan_id,
            "host_id": v.host_id,
            "name": v.name,
            "severity": v.severity,
            "description": v.description,
            "external_id": v.external_id,
            "tool_source": v.tool_source,
            "remediation_status": v.remediation_status,
            "remediation_notes": v.remediation_notes,
            "cvss_score": v.cvss_score,
            "cvss_vector": v.cvss_vector,
            "cvss_version": v.cvss_version,
            "nvd_severity": v.nvd_severity,
            "epss_score": v.epss_score,
            "epss_percentile": v.epss_percentile,
            "enrichment_status": v.enrichment_status,
            "enriched_at": v.enriched_at.isoformat() if v.enriched_at else None,
            "refs": v.refs,
            "weakness_ids": v.weakness_ids,
            "threat_intel": v.threat_intel,
        }
        for v in vulns
    ]}


@router.patch("/vulns/{vuln_id}/remediation")
async def update_vuln_remediation(
    vuln_id: int,
    body: dict,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update remediation status for a vulnerability."""
    status_val = body.get("status")
    if not status_val:
        raise HTTPException(status_code=400, detail="status is required")
    if status_val not in _VALID_REMEDIATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(_VALID_REMEDIATION_STATUSES))}")

    kwargs = {}
    if "notes" in body:
        kwargs["notes"] = body["notes"]
    await repo.update_remediation(session, vuln_id, status_val, **kwargs)
    await session.commit()
    return {"success": True}


@router.patch("/vulns/bulk-remediation")
async def bulk_update_remediation(
    body: dict,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Bulk update remediation status for multiple vulnerabilities."""
    vuln_ids = body.get("vuln_ids", [])
    status_val = body.get("status")
    if not vuln_ids or not status_val:
        raise HTTPException(status_code=400, detail="vuln_ids and status are required")
    if status_val not in _VALID_REMEDIATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(_VALID_REMEDIATION_STATUSES))}")

    kwargs = {}
    if "notes" in body:
        kwargs["notes"] = body["notes"]
    count = await repo.bulk_update_remediation(
        session, vuln_ids, status_val, **kwargs
    )
    await session.commit()
    return {"success": True, "updated": count}


@router.get("/ioc-findings")
async def list_ioc_findings(
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List IOC findings with optional filters."""
    findings = await repo.list_ioc_findings(
        session, scan_id=scan_id, severity=severity, limit=limit, offset=offset,
    )
    return {"findings": [
        {
            "id": f.id,
            "scan_id": f.scan_id,
            "severity": f.severity,
            "score": f.score,
            "file_path": f.file_path,
            "rule_name": f.rule_name,
            "description": f.description,
            "hash_sha256": f.hash_sha256,
            "remediation_status": f.remediation_status,
        }
        for f in findings
    ]}


@router.get("/enrichment-summary")
async def get_enrichment_summary(
    scan_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get enrichment status breakdown for vulnerabilities."""
    return await repo.get_enrichment_summary(session, scan_id=scan_id)


@router.get("/compare/{scan_a}/{scan_b}")
async def compare_scans(
    scan_a: str,
    scan_b: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Compare two scans: new/resolved/common hosts and vulns."""
    return await repo.get_scan_comparison(session, scan_a, scan_b)


@router.get("/audit")
async def list_audit_log(
    action: Optional[str] = None,
    audit_user: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List audit log entries."""
    entries = await repo.list_audit_log(
        session, action=action, user=audit_user, limit=limit, offset=offset,
    )
    return {"entries": [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "action": e.action,
            "user": e.user,
            "source_ip": e.source_ip,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "detail": e.detail,
        }
        for e in entries
    ]}
