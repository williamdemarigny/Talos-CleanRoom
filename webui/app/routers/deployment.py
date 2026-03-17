"""Deployment API router."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
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


class ServiceCredential(BaseModel):
    """A single service's credentials."""
    username: str
    password: str
    note: Optional[str] = None


class CredentialsResponse(BaseModel):
    """Response for service credentials."""
    credentials: dict[str, ServiceCredential]


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


@router.get("/kubeconfig")
async def download_kubeconfig(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Download the kubeconfig file after a successful deployment."""
    deployment = service.get_status()

    if deployment is None or deployment.status != DeploymentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kubeconfig is only available after a successful deployment"
        )

    kubeconfig_path = Path.home() / ".kube" / "config"

    if not kubeconfig_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kubeconfig file not found on server"
        )

    return FileResponse(
        path=str(kubeconfig_path),
        media_type="application/yaml",
        filename="kubeconfig.yaml"
    )


@router.get("/credentials", response_model=CredentialsResponse)
async def get_credentials(
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service)
):
    """Get service credentials after a successful deployment."""
    deployment = service.get_status()

    if deployment is None or deployment.status not in (
        DeploymentStatus.COMPLETED, DeploymentStatus.FAILED
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credentials are only available after a completed or failed deployment"
        )

    if not service.credentials:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No credentials available"
        )

    return CredentialsResponse(credentials=service.credentials)


@router.post("/resume", response_model=DeploymentResponse)
async def resume_deployment(
    from_step: Optional[int] = None,
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service),
):
    """Resume a failed or aborted deployment.

    Optionally specify ``from_step`` to retry from a specific step.
    Logs are preserved (appended, not cleared).
    """
    try:
        deployment = await service.resume_deployment(from_step=from_step)
        return DeploymentResponse(
            success=True,
            message=f"Deployment resumed from step {from_step if from_step is not None else 'last failure'}",
            deployment_id=deployment.id,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/skip-step", response_model=DeploymentResponse)
async def skip_step(
    step_id: int,
    user: dict = Depends(get_current_user),
    service: DeploymentService = Depends(get_deployment_service),
):
    """Mark a step as SKIPPED and resume deployment from the next step."""
    try:
        await service.skip_step(step_id)
        return DeploymentResponse(
            success=True,
            message=f"Step {step_id} skipped, deployment resumed from step {step_id + 1}",
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
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
