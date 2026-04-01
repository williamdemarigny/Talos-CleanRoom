"""Target Lab API router — deploy/destroy Metasploitable3 target VMs."""

import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from talos_common.auth import get_current_user
from app.db import engine as db_engine
from app.services.audit import log_audit
from app.services.target_lab_service import (
    get_target_lab_service,
    TargetLabError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class TemplateType(str, Enum):
    UBUNTU = "ubuntu"
    WINDOWS = "windows"


class DeployRequest(BaseModel):
    template: TemplateType


class ExtendTTLRequest(BaseModel):
    hours: int = Field(4, ge=1, le=24)


@router.get("/templates")
async def list_templates(user: dict = Depends(get_current_user)):
    """List available Metasploitable3 templates."""
    svc = get_target_lab_service()
    return {"templates": svc.get_templates(), "enabled": svc.enabled}


@router.get("/targets")
async def list_targets(user: dict = Depends(get_current_user)):
    """List active target VMs."""
    svc = get_target_lab_service()
    if not svc.enabled:
        return {"targets": [], "enabled": False}
    targets = await svc.list_targets()
    capacity = await svc.get_capacity()
    return {"targets": targets, "capacity": capacity, "enabled": True}


@router.get("/capacity")
async def get_capacity(user: dict = Depends(get_current_user)):
    """Get current target VM capacity."""
    svc = get_target_lab_service()
    if not svc.enabled:
        raise HTTPException(503, "Target Lab is not configured.")
    return await svc.get_capacity()


@router.post("/deploy")
async def deploy_target(
    body: DeployRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Deploy a new Metasploitable3 target VM."""
    svc = get_target_lab_service()
    try:
        result = await svc.deploy_target(body.template.value, user.get("sub", "admin"))
    except TargetLabError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Deploy failed: %s", e)
        raise HTTPException(500, "Deployment failed. Check logs for details.")

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_deploy", user.get("username", "admin"),
                request=request, resource_type="target_vm", resource_id=str(result["vmid"]),
                detail={"template": body.template.value, "ip": result["ip_address"]},
            )
    return result


@router.post("/destroy/{vmid}")
async def destroy_target(
    vmid: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Destroy a target VM."""
    svc = get_target_lab_service()
    try:
        result = await svc.destroy_target(vmid, user.get("sub", "admin"))
    except TargetLabError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Destroy failed for VM %d: %s", vmid, e)
        raise HTTPException(500, "Destroy failed. Check logs for details.")

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_destroy", user.get("username", "admin"),
                request=request, resource_type="target_vm", resource_id=str(vmid),
            )
    return result


@router.post("/extend/{vmid}")
async def extend_ttl(
    vmid: int,
    body: ExtendTTLRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Extend the TTL of a running target VM."""
    svc = get_target_lab_service()
    try:
        result = await svc.extend_ttl(vmid, body.hours, user.get("sub", "admin"))
    except TargetLabError as e:
        raise HTTPException(400, str(e))

    factory = db_engine.get_session_factory()
    if factory:
        async with factory() as session:
            await log_audit(
                session, "target_lab_extend_ttl", user.get("username", "admin"),
                request=request, resource_type="target_vm", resource_id=str(vmid),
                detail={"hours": body.hours},
            )
    return result


@router.get("/status/{vmid}")
async def get_target_status(
    vmid: int,
    user: dict = Depends(get_current_user),
):
    """Get status of a specific target VM."""
    svc = get_target_lab_service()
    target = await svc.get_target(vmid)
    if not target:
        raise HTTPException(404, f"Target VM {vmid} not found.")
    return target
