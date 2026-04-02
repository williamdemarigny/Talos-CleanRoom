"""Target Lab API router — deploy/destroy Vulhub K8s-based vulnerable environments."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from talos_common.auth import get_current_user
from app.db import engine as db_engine
from app.services.audit import log_audit
from app.services.vulhub_target_service import (
    get_vulhub_target_service,
    VulhubTargetError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class DeployRequest(BaseModel):
    env_id: str


class ExtendTTLRequest(BaseModel):
    hours: int = Field(2, ge=1, le=12)


@router.get("/catalog")
async def list_catalog(
    category: Optional[str] = Query(None, description="Filter by category"),
    user: dict = Depends(get_current_user),
):
    """List available Vulhub environments, optionally filtered by category."""
    svc = get_vulhub_target_service()
    catalog = svc.get_catalog(category=category)
    return {"catalog": catalog, "enabled": svc.enabled}


@router.get("/catalog/{env_id}")
async def get_catalog_entry(
    env_id: str,
    user: dict = Depends(get_current_user),
):
    """Get details for a single Vulhub environment."""
    svc = get_vulhub_target_service()
    entry = svc.get_catalog_entry(env_id)
    if not entry:
        raise HTTPException(404, f"Environment '{env_id}' not found in catalog.")
    return entry


@router.get("/targets")
async def list_targets(user: dict = Depends(get_current_user)):
    """List active Vulhub targets."""
    svc = get_vulhub_target_service()
    if not svc.enabled:
        return {"targets": [], "enabled": False}
    targets = await svc.list_targets()
    capacity = await svc.get_capacity()
    return {"targets": targets, "capacity": capacity, "enabled": True}


@router.get("/targets/{target_id}")
async def get_target(
    target_id: int,
    user: dict = Depends(get_current_user),
):
    """Get status of a specific Vulhub target."""
    svc = get_vulhub_target_service()
    target = await svc.get_target(target_id)
    if not target:
        raise HTTPException(404, f"Target {target_id} not found.")
    return target


@router.post("/deploy")
async def deploy_target(
    body: DeployRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Deploy a new Vulhub vulnerable environment."""
    svc = get_vulhub_target_service()
    try:
        result = await svc.deploy_target(body.env_id, user.get("username", "admin"))
    except VulhubTargetError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Vulhub deploy failed: %s", e)
        raise HTTPException(500, "Deployment failed. Check logs for details.")

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_deploy", user.get("username", "admin"),
                request=request, resource_type="vulhub_target",
                resource_id=str(result.get("id", "")),
                detail={"env_id": body.env_id, "namespace": result.get("namespace", "")},
            )
    return result


@router.post("/destroy/{target_id}")
async def destroy_target(
    target_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Destroy a Vulhub target environment."""
    svc = get_vulhub_target_service()
    try:
        result = await svc.destroy_target(target_id, user.get("username", "admin"))
    except VulhubTargetError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Vulhub destroy failed for target %d: %s", target_id, e)
        raise HTTPException(500, "Destroy failed. Check logs for details.")

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_destroy", user.get("username", "admin"),
                request=request, resource_type="vulhub_target",
                resource_id=str(target_id),
            )
    return result


@router.post("/extend/{target_id}")
async def extend_ttl(
    target_id: int,
    body: ExtendTTLRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Extend the TTL of a running Vulhub target."""
    svc = get_vulhub_target_service()
    try:
        result = await svc.extend_ttl(target_id, body.hours)
    except VulhubTargetError as e:
        raise HTTPException(400, str(e))

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_extend_ttl", user.get("username", "admin"),
                request=request, resource_type="vulhub_target",
                resource_id=str(target_id),
                detail={"hours": body.hours},
            )
    return result


@router.get("/capacity")
async def get_capacity(user: dict = Depends(get_current_user)):
    """Get current Vulhub target capacity."""
    svc = get_vulhub_target_service()
    if not svc.enabled:
        raise HTTPException(503, "Target Lab is not configured.")
    return await svc.get_capacity()
