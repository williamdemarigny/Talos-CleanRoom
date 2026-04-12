"""Enrichment API router — trigger, status, and config endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from talos_common.auth import get_current_user
from app.db.engine import get_session
from app.db import repository as repo
from app.config import get_settings
from app.services.enrichment_service import get_enrichment_service

import asyncio

router = APIRouter()


@router.post("/trigger/{scan_id}")
async def trigger_enrichment(
    scan_id: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger enrichment for a specific scan."""
    settings = get_settings()
    if not settings.enrichment_enabled:
        raise HTTPException(status_code=400, detail="Enrichment is not enabled")

    scan = await repo.get_scan(session, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    service = get_enrichment_service()
    if service._running:
        raise HTTPException(status_code=429, detail="Enrichment already running")

    task = asyncio.create_task(service.enrich_scan(scan_id))
    task.add_done_callback(service._handle_task_exception)
    return {"status": "started", "scan_id": scan_id}


@router.post("/trigger-all")
async def trigger_all_enrichment(
    user: dict = Depends(get_current_user),
):
    """Re-enrich all pending/failed vulnerabilities."""
    settings = get_settings()
    if not settings.enrichment_enabled:
        raise HTTPException(status_code=400, detail="Enrichment is not enabled")

    service = get_enrichment_service()
    if service._running:
        raise HTTPException(status_code=429, detail="Enrichment already running")

    task = asyncio.create_task(service.enrich_pending())
    task.add_done_callback(service._handle_task_exception)
    return {"status": "started"}


@router.post("/re-enrich/{scan_id}")
async def re_enrich_scan(
    scan_id: str,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Reset enrichment status and re-enrich a scan."""
    settings = get_settings()
    if not settings.enrichment_enabled:
        raise HTTPException(status_code=400, detail="Enrichment is not enabled")

    scan = await repo.get_scan(session, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    service = get_enrichment_service()
    if service._running:
        raise HTTPException(status_code=429, detail="Enrichment already running")

    # Reset all enriched/failed vulns back to pending
    from sqlalchemy import update
    from app.db.models import Vulnerability
    result = await session.execute(
        update(Vulnerability)
        .where(
            Vulnerability.scan_id == scan_id,
            Vulnerability.enrichment_status.in_(["enriched", "failed"]),
        )
        .values(enrichment_status="pending", enriched_at=None)
    )
    await session.commit()

    task = asyncio.create_task(service.enrich_scan(scan_id))
    task.add_done_callback(service._handle_task_exception)
    return {"status": "started", "scan_id": scan_id, "reset_count": result.rowcount}


@router.get("/status")
async def enrichment_status(
    user: dict = Depends(get_current_user),
):
    """Get current enrichment service status and progress."""
    return get_enrichment_service().get_status()


@router.get("/config")
async def enrichment_config(
    user: dict = Depends(get_current_user),
):
    """Show enrichment configuration (no secrets exposed)."""
    settings = get_settings()
    return {
        "enrichment_enabled": settings.enrichment_enabled,
        "nvd_api_key_configured": bool(settings.nvd_api_key),
        "nvd_rate_limit": settings.nvd_rate_limit_keyed if settings.nvd_api_key else settings.nvd_rate_limit,
        "epss_enabled": settings.epss_enabled,
        "otx_enabled": settings.otx_enabled,
        "otx_api_key_configured": bool(settings.otx_api_key),
        "enrichment_auto_trigger": settings.enrichment_auto_trigger,
        "enrichment_cache_ttl_days": settings.enrichment_cache_ttl_days,
        "enrichment_max_concurrent_nvd": settings.enrichment_max_concurrent_nvd,
    }


@router.get("/summary")
async def enrichment_summary(
    scan_id: str = None,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get enrichment status breakdown for vulnerabilities."""
    return await repo.get_enrichment_summary(session, scan_id=scan_id)
