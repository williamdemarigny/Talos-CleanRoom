"""Deployment API router."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from app.auth import get_current_user
from app.services.deployment_service import get_deployment_service, DeploymentService
from app.models.deployment import DeploymentState, DeploymentStatus, LogEntry

router = APIRouter()


class DeploymentResponse(BaseModel):
    """Response for deployment operations."""
    success: bool
    message: str
    deployment_id: Optional[str] = None


class DeploymentStatusResponse(BaseModel):
    """Response for deployment status."""
    status: DeploymentStatus
    current_step: int
    deployment: Optional[DeploymentState] = None
    is_running: bool


class LogsResponse(BaseModel):
    """Response for deployment logs."""
    logs: List[dict]
    total: int


@router.post("/start", response_model=DeploymentResponse)
async def start_deployment(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Start a new deployment."""
    if service.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deployment already in progress"
        )

    try:
        deployment = await service.start_deployment()
        return DeploymentResponse(
            success=True,
            message="Deployment started",
            deployment_id=deployment.id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/abort", response_model=DeploymentResponse)
async def abort_deployment(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Abort the current deployment."""
    if not service.is_running():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No deployment in progress"
        )

    success = await service.abort_deployment()
    return DeploymentResponse(
        success=success,
        message="Deployment aborted" if success else "Failed to abort deployment"
    )


@router.get("/status", response_model=DeploymentStatusResponse)
async def get_deployment_status(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Get current deployment status."""
    deployment = service.get_status()

    if deployment is None:
        return DeploymentStatusResponse(
            status=DeploymentStatus.IDLE,
            current_step=0,
            deployment=None,
            is_running=False
        )

    return DeploymentStatusResponse(
        status=deployment.status,
        current_step=deployment.current_step,
        deployment=deployment,
        is_running=service.is_running()
    )


@router.get("/logs", response_model=LogsResponse)
async def get_deployment_logs(
    step_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Get deployment logs."""
    logs = service.logs

    # Filter by step if specified
    if step_id is not None:
        logs = [log for log in logs if log.step_id == step_id]

    total = len(logs)

    # Apply pagination
    logs = logs[offset:offset + limit]

    return LogsResponse(
        logs=[log.model_dump() for log in logs],
        total=total
    )


@router.post("/cleanup", response_model=DeploymentResponse)
async def run_cleanup(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Run cleanup (terraform destroy)."""
    if service.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot run cleanup while deployment is in progress"
        )

    success = await service.cleanup()
    return DeploymentResponse(
        success=success,
        message="Cleanup completed" if success else "Cleanup failed"
    )
