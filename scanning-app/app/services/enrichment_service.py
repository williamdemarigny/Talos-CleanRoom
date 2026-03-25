"""Vulnerability enrichment service — NVD (CVSS/CPE), EPSS, and OTX integration.

Queries external APIs after scan completion to enrich CVE-bearing
vulnerabilities with authoritative severity scores, exploit probability,
and threat intelligence context.
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Optional

import httpx

from app.config import get_settings
from app.db import engine as db_engine
from app.db import repository as repo

logger = logging.getLogger(__name__)

# Strict CVE ID validation — primary SSRF defense
_CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")

# Application-level domain allowlist
_ALLOWED_HOSTS = frozenset([
    "services.nvd.nist.gov",
    "api.first.org",
    "otx.alienvault.com",
])

# NVD API base URL
_NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# EPSS API base URL
_EPSS_API_URL = "https://api.first.org/data/v1/epss"

# CVSS severity thresholds
_CVSS_SEVERITY = [
    (9.0, "critical"),
    (7.0, "high"),
    (4.0, "medium"),
    (0.1, "low"),
]


def _derive_nvd_severity(score: Optional[float]) -> Optional[str]:
    """Map CVSS score to severity string."""
    if score is None:
        return None
    for threshold, label in _CVSS_SEVERITY:
        if score >= threshold:
            return label
    return "none"


# ── Singleton ─────────────────────────────────────────────────────

_enrichment_service: Optional["EnrichmentService"] = None


def get_enrichment_service() -> "EnrichmentService":
    """Return the singleton enrichment service instance."""
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = EnrichmentService()
    return _enrichment_service


# ── Service ───────────────────────────────────────────────────────

class EnrichmentService:
    """Background enrichment of CVE-bearing vulnerabilities via NVD and EPSS."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(1)  # serialize enrichment runs
        self._nvd_last_call = 0.0
        self._running = False
        self._progress = 0
        self._total = 0
        self._status = "idle"

    def _ensure_client(self):
        """Lazily create the httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                verify=True,
                timeout=httpx.Timeout(connect=5.0, read=15.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                follow_redirects=False,
                headers={"User-Agent": "TalosCleanRoom/1.0"},
            )

    # ── Public API ────────────────────────────────────────────────

    async def enrich_scan(self, scan_id: str, broadcast_callback=None):
        """Enrich all CVE-bearing vulns from a completed scan.

        Args:
            scan_id: The scan ID to enrich.
            broadcast_callback: Optional async callable to broadcast progress.
        """
        settings = get_settings()
        if not settings.enrichment_enabled:
            return

        async with self._semaphore:
            self._running = True
            self._status = "running"
            self._progress = 0
            try:
                await self._do_enrich(scan_id, settings, broadcast_callback)
            except Exception as exc:
                logger.error("Enrichment failed for scan %s: %s", scan_id, exc)
                self._status = "failed"
            finally:
                self._running = False
                if self._status == "running":
                    self._status = "idle"

    async def enrich_pending(self, limit: int = 100):
        """Re-enrich any pending/failed vulns (manual trigger)."""
        settings = get_settings()
        if not settings.enrichment_enabled:
            return

        session_factory = db_engine.get_session_factory()
        if session_factory is None:
            return

        async with session_factory() as session:
            vulns = await repo.get_vulns_pending_enrichment(session, limit=limit)
            if not vulns:
                logger.info("No pending vulns to enrich")
                return
            # Group by scan_id and enrich each scan's vulns
            scan_ids = {v.scan_id for v in vulns}

        for sid in scan_ids:
            await self.enrich_scan(sid)

    def get_status(self) -> dict:
        """Return current enrichment status and progress."""
        return {
            "status": self._status,
            "running": self._running,
            "progress": self._progress,
            "total": self._total,
        }

    async def close(self):
        """Close the httpx client on shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _handle_task_exception(self, task: asyncio.Task):
        """Log unhandled exceptions from background enrichment tasks."""
        if not task.cancelled() and task.exception():
            logger.error("Enrichment task failed: %s", task.exception())

    # ── Internal ──────────────────────────────────────────────────

    async def _do_enrich(self, scan_id: str, settings, broadcast_callback):
        """Core enrichment logic: NVD pass → EPSS pass → DB update."""
        self._ensure_client()

        # 0. Connectivity pre-check
        if not await self._check_connectivity():
            logger.warning("NVD unreachable — skipping enrichment for scan %s", scan_id)
            return

        session_factory = db_engine.get_session_factory()
        if session_factory is None:
            return

        # 1. Read pending vulns (short session)
        async with session_factory() as session:
            vulns = await repo.get_vulns_pending_enrichment(session, scan_id=scan_id)
            if not vulns:
                logger.info("No CVE-bearing vulns to enrich for scan %s", scan_id)
                return

            # Also find vulns with CVEs in refs but no external_id
            all_vulns_with_refs = []
            from sqlalchemy import select
            from app.db.models import Vulnerability
            result = await session.execute(
                select(Vulnerability).where(
                    Vulnerability.scan_id == scan_id,
                    Vulnerability.external_id.is_(None),
                    Vulnerability.refs.isnot(None),
                    Vulnerability.enrichment_status == "skipped",
                )
            )
            for v in result.scalars().all():
                if v.refs:
                    cves = [r for r in v.refs if isinstance(r, str) and _CVE_PATTERN.match(r)]
                    if cves:
                        v.external_id = cves[0]
                        v.enrichment_status = "pending"
                        all_vulns_with_refs.append(v)
            if all_vulns_with_refs:
                await session.commit()
                vulns.extend(all_vulns_with_refs)

        # 2. Extract unique CVE IDs (dedup)
        unique_cves = sorted({v.external_id for v in vulns if v.external_id and _CVE_PATTERN.match(v.external_id)})
        if not unique_cves:
            logger.info("No valid CVE IDs found for scan %s", scan_id)
            return

        self._total = len(unique_cves)
        self._progress = 0
        logger.info("Enriching %d unique CVEs for scan %s", len(unique_cves), scan_id)

        # 3. NVD pass — query per unique CVE, cache results
        nvd_cache = {}
        rate_limit = settings.nvd_rate_limit_keyed if settings.nvd_api_key else settings.nvd_rate_limit

        for cve_id in unique_cves:
            data = await self._query_nvd(cve_id, settings)
            if data:
                nvd_cache[cve_id] = data
            self._progress += 1

            if broadcast_callback:
                try:
                    await broadcast_callback({
                        "type": "enrichment_update",
                        "data": {
                            "scan_id": scan_id,
                            "progress": self._progress,
                            "total": self._total,
                            "status": "running",
                        },
                    })
                except Exception:
                    pass

            # Rate limit between NVD calls
            await asyncio.sleep(rate_limit)

        # 4. EPSS pass — bulk query
        epss_data = {}
        if settings.epss_enabled:
            epss_data = await self._query_epss_batch(unique_cves)

        # 5. Write enrichment data (short session)
        enriched_count = 0
        async with session_factory() as session:
            for cve_id in unique_cves:
                nvd = nvd_cache.get(cve_id, {})
                epss = epss_data.get(cve_id, {})

                enrichment_data = {
                    "enrichment_status": "enriched" if nvd or epss else "failed",
                    "enriched_at": datetime.utcnow(),
                    "enrichment_source": ",".join(
                        s for s in [
                            "nvd" if nvd else None,
                            "epss" if epss else None,
                        ] if s
                    ) or None,
                }

                # NVD fields
                if nvd:
                    enrichment_data.update({
                        "cvss_score": nvd.get("cvss_score"),
                        "cvss_vector": nvd.get("cvss_vector"),
                        "cvss_version": nvd.get("cvss_version"),
                        "nvd_severity": nvd.get("nvd_severity"),
                        "cpe_matches": nvd.get("cpe_matches"),
                        "weakness_ids": nvd.get("weakness_ids"),
                    })

                # EPSS fields
                if epss:
                    enrichment_data.update({
                        "epss_score": epss.get("epss"),
                        "epss_percentile": epss.get("percentile"),
                    })

                rows = await repo.update_enrichment_by_cve(
                    session, scan_id, cve_id, **enrichment_data
                )
                enriched_count += rows

            await session.commit()

        logger.info(
            "Enrichment complete for scan %s: %d CVEs queried, %d vuln rows updated",
            scan_id, len(unique_cves), enriched_count,
        )
        self._status = "idle"

        if broadcast_callback:
            try:
                await broadcast_callback({
                    "type": "enrichment_update",
                    "data": {
                        "scan_id": scan_id,
                        "progress": self._total,
                        "total": self._total,
                        "status": "completed",
                    },
                })
            except Exception:
                pass

    # ── API Clients ───────────────────────────────────────────────

    async def _check_connectivity(self) -> bool:
        """Quick HEAD check to NVD API."""
        self._ensure_client()
        try:
            resp = await self._client.head(_NVD_API_URL, timeout=5.0)
            return resp.status_code < 500
        except Exception:
            return False

    async def _query_nvd(self, cve_id: str, settings) -> Optional[dict]:
        """Query NVD API v2.0 for a single CVE."""
        if not _CVE_PATTERN.match(cve_id):
            return None

        self._ensure_client()
        headers = {}
        if settings.nvd_api_key:
            headers["apiKey"] = settings.nvd_api_key

        try:
            resp = await self._client.get(
                _NVD_API_URL,
                params={"cveId": cve_id},
                headers=headers,
            )

            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                logger.warning("NVD rate limited on %s — backing off", cve_id)
                await asyncio.sleep(30)
                return None
            resp.raise_for_status()

            data = resp.json()
            vulns = data.get("vulnerabilities", [])
            if not vulns:
                return None

            cve_data = vulns[0].get("cve", {})
            return self._parse_nvd_response(cve_data)

        except httpx.TimeoutException:
            logger.warning("NVD timeout for %s", cve_id)
            return None
        except Exception as exc:
            logger.warning("NVD query failed for %s: %s", cve_id, exc)
            return None

    def _parse_nvd_response(self, cve_data: dict) -> dict:
        """Extract CVSS, CPE, and weakness data from NVD response."""
        result = {}
        metrics = cve_data.get("metrics", {})

        # CVSS fallback chain: v4.0 > v3.1 > v3.0 > v2.0
        cvss_parsed = False
        for version_key, version_label in [
            ("cvssMetricV40", "4.0"),
            ("cvssMetricV31", "3.1"),
            ("cvssMetricV30", "3.0"),
            ("cvssMetricV2", "2.0"),
        ]:
            metric_list = metrics.get(version_key, [])
            if metric_list:
                metric = metric_list[0]
                cvss_data = metric.get("cvssData", {})
                result["cvss_score"] = cvss_data.get("baseScore")
                result["cvss_vector"] = cvss_data.get("vectorString")
                result["cvss_version"] = version_label
                result["nvd_severity"] = _derive_nvd_severity(result["cvss_score"])
                cvss_parsed = True
                break

        if not cvss_parsed:
            result["cvss_score"] = None
            result["cvss_vector"] = None
            result["cvss_version"] = None
            result["nvd_severity"] = None

        # CPE matches
        cpe_matches = []
        for config in cve_data.get("configurations", []):
            for node in config.get("nodes", []):
                for match in node.get("cpeMatch", []):
                    criteria = match.get("criteria")
                    if criteria:
                        cpe_matches.append(criteria)
        result["cpe_matches"] = cpe_matches or None

        # Weaknesses (CWE IDs)
        weakness_ids = []
        for weakness in cve_data.get("weaknesses", []):
            for desc in weakness.get("description", []):
                val = desc.get("value", "")
                if val.startswith("CWE-"):
                    weakness_ids.append(val)
        result["weakness_ids"] = weakness_ids or None

        return result

    async def _query_epss_batch(self, cve_ids: list) -> dict:
        """Bulk query EPSS API for exploit probability scores."""
        self._ensure_client()
        epss_data = {}

        # Chunk into groups of 100 (URL length constraint)
        for i in range(0, len(cve_ids), 100):
            chunk = cve_ids[i:i + 100]
            try:
                resp = await self._client.get(
                    _EPSS_API_URL,
                    params={"cve": ",".join(chunk)},
                    timeout=20.0,
                )
                resp.raise_for_status()
                body = resp.json()
                for entry in body.get("data", []):
                    cve = entry.get("cve")
                    if cve:
                        epss_data[cve] = {
                            "epss": float(entry.get("epss", 0)),
                            "percentile": float(entry.get("percentile", 0)),
                        }
            except Exception as exc:
                logger.warning("EPSS batch query failed: %s", exc)

            if i + 100 < len(cve_ids):
                await asyncio.sleep(1.0)

        return epss_data
