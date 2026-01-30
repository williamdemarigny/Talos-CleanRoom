"""Configuration API router."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any

from app.auth import get_current_user
from app.services.config_service import ConfigService
from app.models.config import ConfigValidationResult

router = APIRouter()


def get_config_service() -> ConfigService:
    """Get config service instance."""
    return ConfigService()


class ConfigResponse(BaseModel):
    """Generic config response."""
    success: bool
    data: Dict[str, Any]


class UpdateConfigRequest(BaseModel):
    """Request to update configuration."""
    config: Dict[str, Any]


@router.get("/terraform")
async def get_terraform_config(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Get Terraform configuration (cluster.auto.tfvars)."""
    result = await service.get_terraform_config()
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )
    return result


@router.put("/terraform")
async def update_terraform_config(
    request: UpdateConfigRequest,
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Update Terraform configuration."""
    result = await service.update_terraform_config(request.config)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to update configuration")
        )
    return result


@router.get("/talos/env")
async def get_talos_env(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Get Talos environment configuration (talenv.yaml)."""
    result = await service.get_talos_env()
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )
    return result


@router.get("/talos/config")
async def get_talos_config(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Get Talos cluster configuration (talconfig.yaml)."""
    result = await service.get_talos_config()
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )
    return result


@router.get("/all")
async def get_all_config(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Get all configuration files."""
    return await service.get_all_config()


@router.get("/validate", response_model=ConfigValidationResult)
async def validate_config(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Validate all configuration files."""
    return await service.validate_config()


@router.post("/regenerate")
async def regenerate_talos_config(
    user: dict = Depends(get_current_user),
    service: ConfigService = Depends(get_config_service)
):
    """Regenerate Talos configuration from Terraform variables.

    This runs tfvars-to-talos-env.sh to sync Terraform config with Talos.
    """
    from app.services.process_manager import ProcessManager

    pm = ProcessManager()
    script_path = service.repo_root / "Resources" / "IAC-DNS" / "tfvars-to-talos-env.sh"

    if not script_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Script not found: {script_path}"
        )

    result = await pm.run_command_simple(
        ["bash", str(script_path), "--backup"],
        cwd=script_path.parent
    )

    return {
        "success": result.success,
        "output": result.output
    }
