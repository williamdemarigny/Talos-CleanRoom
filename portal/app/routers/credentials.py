"""Credentials API — serves vault contents to authenticated users."""

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException

from talos_common.auth import get_current_user

router = APIRouter()

VAULT_PATH = Path("/etc/credentials/credentials.yaml")


@router.get("/")
async def get_credentials(user: dict = Depends(get_current_user)):
    """Return all service credentials from the mounted vault."""
    if not VAULT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Credential vault not available. Run generate-secrets.sh and redeploy.",
        )
    try:
        data = yaml.safe_load(VAULT_PATH.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read vault: {exc}")
    return data
