"""Vulnerability enrichment service — NVD (CVSS/CPE), EPSS, and OTX integration.

Queries external APIs after scan completion to enrich CVE-bearing
vulnerabilities with authoritative severity scores, exploit probability,
and threat intelligence context.

Phase 2 additions: CVE cache (PostgreSQL), concurrent NVD requests,
and prefetch-during-scan support.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import get_settings
from app.db import engine as db_engine
from app.db import repository as repo

logger = logging.getLogger(__name__)

# Strict CVE ID validation — primary SSRF defense
_CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")

# NVD API base URL
_NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# EPSS API base URL
_EPSS_API_URL = "https://api.first.org/data/v1/epss"

# OTX API base URL
_OTX_API_URL = "https://otx.alienvault.com/api/v1/indicators/cve"

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
        self._enrich_semaphore = asyncio.Semaphore(1)  # serialize enrichment runs
        self._nvd_rate_limiter = _TokenBucket(rate=0.15)  # default: ~6.5s between
        self._running = False
        self._progress = 0
        self._total = 0
        self._status = "idle"
        self._cache_stats = {"hits": 0, "misses": 0}

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
        """Enrich all CVE-bearing vulns from a completed scan."""
        settings = get_settings()
        if not settings.enrichment_enabled:
            return

        async with self._enrich_semaphore:
            self._running = True
            self._status = "running"
            self._progress = 0
            self._cache_stats = {"hits": 0, "misses": 0}
            try:
                await self._do_enrich(scan_id, settings, broadcast_callback)
            except Exception as exc:
                logger.error("Enrichment failed for scan %s: %s", scan_id, exc)
                self._status = "failed"
            finally:
                self._running = False
                if self._status == "running":
                    self._status = "idle"

    async def prefetch_cves(self, cve_ids: list):
        """Prefetch NVD+EPSS data into cache without updating vuln rows.

        Called after each tool's results are persisted (fire-and-forget).
        Only populates the cve_cache table — does NOT update vulnerability rows.
        """
        settings = get_settings()
        if not settings.enrichment_enabled:
            return

        self._ensure_client()
        session_factory = db_engine.get_session_factory()
        if session_factory is None:
            return

        valid_cves = [c for c in set(cve_ids) if _CVE_PATTERN.match(c)]
        if not valid_cves:
            return

        # Filter out CVEs already in cache
        async with session_factory() as session:
            cached = await repo.get_cached_cves(session, valid_cves)
        uncached = [c for c in valid_cves if c not in cached]
        if not uncached:
            logger.debug("Prefetch: all %d CVEs already cached", len(valid_cves))
            return

        logger.info("Prefetching %d uncached CVEs into cache", len(uncached))

        # Configure rate limit
        rate = 1.0 / settings.nvd_rate_limit_keyed if settings.nvd_api_key else 1.0 / settings.nvd_rate_limit
        self._nvd_rate_limiter = _TokenBucket(rate=rate)
        nvd_semaphore = asyncio.Semaphore(settings.enrichment_max_concurrent_nvd)

        async def fetch_one(cve_id):
            async with nvd_semaphore:
                await self._nvd_rate_limiter.acquire()
                return cve_id, await self._query_nvd(cve_id, settings)

        # Concurrent NVD fetch
        tasks = [fetch_one(cve) for cve in uncached]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # EPSS bulk fetch
        epss_data = {}
        if settings.epss_enabled:
            epss_data = await self._query_epss_batch(uncached)

        # Write to cache
        ttl = timedelta(days=settings.enrichment_cache_ttl_days)
        now = datetime.utcnow()
        async with session_factory() as session:
            for item in results:
                if isinstance(item, Exception):
                    continue
                cve_id, nvd = item
                if not nvd:
                    continue
                epss = epss_data.get(cve_id, {})
                await repo.upsert_cve_cache(
                    session, cve_id,
                    cvss_score=nvd.get("cvss_score"),
                    cvss_vector=nvd.get("cvss_vector"),
                    cvss_version=nvd.get("cvss_version"),
                    nvd_severity=nvd.get("nvd_severity"),
                    weakness_ids=nvd.get("weakness_ids"),
                    cpe_matches=nvd.get("cpe_matches"),
                    epss_score=epss.get("epss"),
                    epss_percentile=epss.get("percentile"),
                    fetched_at=now,
                    expires_at=now + ttl,
                )
            await session.commit()

        logger.info("Prefetch complete: %d CVEs cached", sum(1 for r in results if not isinstance(r, Exception) and r[1]))

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
            "cache_hits": self._cache_stats.get("hits", 0),
            "cache_misses": self._cache_stats.get("misses", 0),
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
        """Core enrichment: cache check → NVD (concurrent) → EPSS → DB update."""
        self._ensure_client()

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
                        vulns.append(v)
            await session.commit()

        # 2. Extract unique CVE IDs (dedup)
        unique_cves = sorted({v.external_id for v in vulns if v.external_id and _CVE_PATTERN.match(v.external_id)})
        if not unique_cves:
            logger.info("No valid CVE IDs found for scan %s", scan_id)
            return

        self._total = len(unique_cves)
        self._progress = 0
        logger.info("Enriching %d unique CVEs for scan %s", len(unique_cves), scan_id)

        # 3. Check cache first (short session)
        nvd_cache = {}
        uncached_cves = []
        async with session_factory() as session:
            cached_entries = await repo.get_cached_cves(session, unique_cves)
            for cve_id in unique_cves:
                if cve_id in cached_entries:
                    entry = cached_entries[cve_id]
                    nvd_cache[cve_id] = {
                        "cvss_score": entry.cvss_score,
                        "cvss_vector": entry.cvss_vector,
                        "cvss_version": entry.cvss_version,
                        "nvd_severity": entry.nvd_severity,
                        "weakness_ids": entry.weakness_ids,
                        "cpe_matches": entry.cpe_matches,
                    }
                    self._cache_stats["hits"] += 1
                else:
                    uncached_cves.append(cve_id)
                    self._cache_stats["misses"] += 1

        logger.info("Cache: %d hits, %d misses", self._cache_stats["hits"], self._cache_stats["misses"])

        # 4. NVD pass — concurrent requests for uncached CVEs
        if uncached_cves:
            # Connectivity pre-check
            if not await self._check_connectivity():
                logger.warning("NVD unreachable — skipping NVD enrichment for scan %s", scan_id)
            else:
                rate = 1.0 / settings.nvd_rate_limit_keyed if settings.nvd_api_key else 1.0 / settings.nvd_rate_limit
                self._nvd_rate_limiter = _TokenBucket(rate=rate)
                nvd_semaphore = asyncio.Semaphore(settings.enrichment_max_concurrent_nvd)

                async def fetch_and_track(cve_id):
                    async with nvd_semaphore:
                        await self._nvd_rate_limiter.acquire()
                        data = await self._query_nvd(cve_id, settings)
                        self._progress += 1
                        if broadcast_callback:
                            try:
                                await broadcast_callback({
                                    "type": "enrichment_update",
                                    "data": {
                                        "scan_id": scan_id,
                                        "progress": self._progress + self._cache_stats["hits"],
                                        "total": self._total,
                                        "status": "running",
                                    },
                                })
                            except Exception:
                                pass
                        return cve_id, data

                tasks = [fetch_and_track(cve) for cve in uncached_cves]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Write results to both nvd_cache dict and DB cache
                ttl = timedelta(days=settings.enrichment_cache_ttl_days)
                now = datetime.utcnow()
                async with session_factory() as session:
                    for item in results:
                        if isinstance(item, Exception):
                            logger.warning("NVD fetch failed: %s", item)
                            continue
                        cve_id, data = item
                        if data:
                            nvd_cache[cve_id] = data
                            await repo.upsert_cve_cache(
                                session, cve_id,
                                cvss_score=data.get("cvss_score"),
                                cvss_vector=data.get("cvss_vector"),
                                cvss_version=data.get("cvss_version"),
                                nvd_severity=data.get("nvd_severity"),
                                weakness_ids=data.get("weakness_ids"),
                                cpe_matches=data.get("cpe_matches"),
                                fetched_at=now,
                                expires_at=now + ttl,
                            )
                    await session.commit()

        # Mark progress for cached CVEs
        self._progress = self._total

        # 5. EPSS pass — bulk query all unique CVEs (cached EPSS may be stale)
        epss_data = {}
        if settings.epss_enabled:
            epss_data = await self._query_epss_batch(unique_cves)
            # Update EPSS in cache for freshness
            if epss_data:
                async with session_factory() as session:
                    for cve_id, epss in epss_data.items():
                        await repo.upsert_cve_cache(
                            session, cve_id,
                            epss_score=epss.get("epss"),
                            epss_percentile=epss.get("percentile"),
                            fetched_at=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(days=settings.enrichment_cache_ttl_days),
                        )
                    await session.commit()

        # 6. OTX pass — per-CVE threat intelligence (if enabled)
        otx_data = {}
        if settings.otx_enabled and settings.otx_api_key:
            otx_data = await self._query_otx_batch(unique_cves, settings)

        # 7. Write enrichment data to vuln rows (short session, bulk by CVE)
        enriched_count = 0
        async with session_factory() as session:
            for cve_id in unique_cves:
                nvd = nvd_cache.get(cve_id, {})
                epss = epss_data.get(cve_id, {})
                otx = otx_data.get(cve_id)

                sources = [s for s in [
                    "nvd" if nvd else None,
                    "epss" if epss else None,
                    "otx" if otx else None,
                ] if s]

                enrichment_data = {
                    "enrichment_status": "enriched" if nvd or epss else "failed",
                    "enriched_at": datetime.utcnow(),
                    "enrichment_source": ",".join(sources) or None,
                }

                if nvd:
                    enrichment_data.update({
                        "cvss_score": nvd.get("cvss_score"),
                        "cvss_vector": nvd.get("cvss_vector"),
                        "cvss_version": nvd.get("cvss_version"),
                        "nvd_severity": nvd.get("nvd_severity"),
                        "cpe_matches": nvd.get("cpe_matches"),
                        "weakness_ids": nvd.get("weakness_ids"),
                    })

                if epss:
                    enrichment_data.update({
                        "epss_score": epss.get("epss"),
                        "epss_percentile": epss.get("percentile"),
                    })

                if otx:
                    enrichment_data["threat_intel"] = otx

                rows = await repo.update_enrichment_by_cve(
                    session, scan_id, cve_id, **enrichment_data
                )
                enriched_count += rows

            await session.commit()

        logger.info(
            "Enrichment complete for scan %s: %d CVEs (%d cached, %d fetched), %d vuln rows updated",
            scan_id, len(unique_cves), self._cache_stats["hits"],
            self._cache_stats["misses"], enriched_count,
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
                logger.warning("NVD rate limited on %s — backing off 30s", cve_id)
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


    async def _query_otx(self, cve_id: str, settings) -> Optional[dict]:
        """Query AlienVault OTX for threat intelligence on a CVE."""
        if not _CVE_PATTERN.match(cve_id):
            return None

        self._ensure_client()
        try:
            resp = await self._client.get(
                f"{_OTX_API_URL}/{cve_id}/general",
                headers={"X-OTX-API-KEY": settings.otx_api_key},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            pulse_info = data.get("pulse_info", {})
            pulse_count = pulse_info.get("count", 0)
            if pulse_count == 0:
                return None

            # Extract tags and adversaries from pulses
            tags = set()
            adversaries = set()
            for pulse in pulse_info.get("pulses", [])[:20]:
                for tag in pulse.get("tags", []):
                    tags.add(tag.lower())
                adversary = pulse.get("adversary")
                if adversary:
                    adversaries.add(adversary)

            return {
                "otx_pulse_count": pulse_count,
                "otx_tags": sorted(tags)[:20],
                "otx_adversaries": sorted(adversaries),
            }

        except Exception as exc:
            logger.warning("OTX query failed for %s: %s", cve_id, exc)
            return None

    async def _query_otx_batch(self, cve_ids: list, settings) -> dict:
        """Query OTX for multiple CVEs with rate limiting."""
        otx_data = {}
        for cve_id in cve_ids:
            result = await self._query_otx(cve_id, settings)
            if result:
                otx_data[cve_id] = result
            await asyncio.sleep(0.5)  # OTX rate limit: ~2 req/s
        return otx_data


# ── Rate Limiter ──────────────────────────────────────────────────

class _TokenBucket:
    """Simple async token bucket rate limiter for NVD API calls."""

    def __init__(self, rate: float = 0.15):
        """Args: rate = tokens per second (0.15 = ~6.5s between calls)."""
        self._rate = rate
        self._tokens = 1.0
        self._max_tokens = 1.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Wait and retry
            await asyncio.sleep(0.5)
