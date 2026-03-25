"""Export API router — CSV and JSON export of scan results."""

import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from talos_common.auth import get_current_user
from app.db.engine import get_session
from app.db import repository as repo
from app.services.audit import log_audit

router = APIRouter()


def _csv_safe(value: str) -> str:
    """Prefix values starting with formula characters to prevent CSV injection."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@router.get("/vulns/csv")
async def export_vulns_csv(
    http_request: Request,
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    remediation_status: Optional[str] = None,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Export vulnerabilities as CSV."""
    await log_audit(
        session, "export.vulns_csv", user["username"],
        request=http_request, resource_type="export",
        detail={"scan_id": scan_id, "severity": severity},
    )
    vulns = await repo.list_vulns(
        session, scan_id=scan_id, severity=severity,
        remediation_status=remediation_status, limit=10000, offset=0,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Scan ID", "Host ID", "Name", "Severity",
        "External ID", "Tool Source", "Remediation Status",
        "Remediation Notes", "Description",
        "CVSS Score", "CVSS Vector", "CVSS Version", "NVD Severity",
        "EPSS Score", "EPSS Percentile", "Enrichment Status",
    ])
    for v in vulns:
        writer.writerow([
            v.id, v.scan_id, v.host_id, _csv_safe(v.name), v.severity,
            v.external_id or "", v.tool_source or "",
            v.remediation_status or "", _csv_safe(v.remediation_notes or ""),
            _csv_safe((v.description or "")[:500]),
            v.cvss_score if v.cvss_score is not None else "",
            v.cvss_vector or "", v.cvss_version or "",
            v.nvd_severity or "",
            f"{v.epss_score:.4f}" if v.epss_score is not None else "",
            f"{v.epss_percentile:.4f}" if v.epss_percentile is not None else "",
            v.enrichment_status or "skipped",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vulnerabilities.csv"},
    )


@router.get("/vulns/json")
async def export_vulns_json(
    http_request: Request,
    scan_id: Optional[str] = None,
    severity: Optional[str] = None,
    remediation_status: Optional[str] = None,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Export vulnerabilities as JSON."""
    await log_audit(
        session, "export.vulns_json", user["username"],
        request=http_request, resource_type="export",
        detail={"scan_id": scan_id, "severity": severity},
    )
    vulns = await repo.list_vulns(
        session, scan_id=scan_id, severity=severity,
        remediation_status=remediation_status, limit=10000, offset=0,
    )

    data = [
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
            "refs": v.refs,
            "tags": v.tags,
            "cvss_score": v.cvss_score,
            "cvss_vector": v.cvss_vector,
            "cvss_version": v.cvss_version,
            "nvd_severity": v.nvd_severity,
            "epss_score": v.epss_score,
            "epss_percentile": v.epss_percentile,
            "enrichment_status": v.enrichment_status,
            "enriched_at": v.enriched_at.isoformat() if v.enriched_at else None,
            "cpe_matches": v.cpe_matches,
            "weakness_ids": v.weakness_ids,
            "threat_intel": v.threat_intel,
        }
        for v in vulns
    ]

    output = io.StringIO()
    json.dump(data, output, indent=2)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=vulnerabilities.json"},
    )


@router.get("/scan/{scan_id}/json")
async def export_scan_json(
    scan_id: str,
    http_request: Request,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Export full scan report as JSON."""
    await log_audit(
        session, "export.scan_json", user["username"],
        request=http_request, resource_type="scan", resource_id=scan_id,
    )
    scan = await repo.get_scan(session, scan_id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    data = {
        "id": scan.id,
        "scan_type": scan.scan_type,
        "target": scan.target,
        "profile": scan.profile,
        "status": scan.status,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "hosts": [
            {
                "ip": h.ip,
                "os": h.os,
                "hostnames": h.hostnames,
                "services": [
                    {"port": s.port, "protocol": s.protocol, "name": s.name, "version": s.version}
                    for s in h.services
                ],
                "vulnerabilities": [
                    {
                        "name": v.name, "severity": v.severity,
                        "external_id": v.external_id, "description": v.description,
                        "tool_source": v.tool_source,
                        "remediation_status": v.remediation_status,
                        "cvss_score": v.cvss_score,
                        "cvss_vector": v.cvss_vector,
                        "cvss_version": v.cvss_version,
                        "nvd_severity": v.nvd_severity,
                        "epss_score": v.epss_score,
                        "epss_percentile": v.epss_percentile,
                        "enrichment_status": v.enrichment_status,
                        "cpe_matches": v.cpe_matches,
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
                "severity": f.severity, "score": f.score,
                "file_path": f.file_path, "rule_name": f.rule_name,
                "description": f.description, "hash_sha256": f.hash_sha256,
            }
            for f in scan.ioc_findings
        ],
    }

    output = io.StringIO()
    json.dump(data, output, indent=2)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=scan-{scan_id}.json"},
    )
