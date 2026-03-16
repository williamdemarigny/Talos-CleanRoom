"""Portal API router — generates one-time auth codes for cross-domain login.

The portal is the only app that GENERATES codes. The target apps
(Deployment Console, Scanning Console) use the shared exchange router
to REDEEM codes. See docs/vuln-management-plan.md Appendix A.
"""

import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import talos_common
from talos_common.auth import get_current_user

router = APIRouter()

# One-time code TTL (seconds)
CODE_TTL = 60


class ExchangeCodeRequest(BaseModel):
    """Request to generate a one-time auth code for a target app."""
    target: str  # "deployment" or "scanning"


class ExchangeCodeResponse(BaseModel):
    """Response with the generated code and redirect URL."""
    code: str
    redirect_url: str


@router.post("/exchange-code", response_model=ExchangeCodeResponse)
async def generate_exchange_code(
    request: ExchangeCodeRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a one-time opaque code for cross-domain authentication.

    The code is HMAC-signed with the derived code_exchange_key (shared
    across all apps via the same SECRET_KEY). Format:
    ``<random>:<exp>:<username>:<signature>``

    The target app verifies the HMAC and expiry, then mints its own JWT.
    """
    settings = talos_common.get_settings()

    # Determine target URL
    if request.target == "deployment":
        base_url = settings.deployment_console_url
    elif request.target == "scanning":
        base_url = settings.scanning_console_url
    else:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unknown target: {request.target}")

    # Build the code
    random_part = secrets.token_hex(16)
    exp = str(int(time.time()) + CODE_TTL)
    username = user["username"]

    sign_payload = f"{random_part}:{exp}:{username}".encode()
    signature = hmac.new(
        settings.code_exchange_key.encode(), sign_payload, hashlib.sha256
    ).hexdigest()

    code = f"{random_part}:{exp}:{username}:{signature}"

    # Build redirect URL
    redirect_url = f"{base_url}?code={code}"

    return ExchangeCodeResponse(code=code, redirect_url=redirect_url)
