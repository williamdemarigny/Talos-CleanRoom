"""Shared authentication API router.

Provides login/logout/me endpoints that work with any app inheriting
from BaseAppSettings.  Each app includes this router at startup:

    from talos_common.routers.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth")
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel

import talos_common
from talos_common.auth import authenticate_user, create_access_token, get_current_user

router = APIRouter()


class Token(BaseModel):
    """Token response model."""
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class UserInfo(BaseModel):
    """User information response."""
    username: str


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    response: Response,
    form_data: LoginRequest,
    settings=Depends(talos_common.get_settings),
):
    """Authenticate user and return JWT token."""
    if not authenticate_user(form_data.username, form_data.password, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(form_data.username, settings)

    # Set secure flag only when behind TLS (direct HTTP in LXC won't send
    # Secure cookies, breaking login).  X-Forwarded-Proto is set by Traefik.
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )

    # Also set cookie for browser-based access
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_https,
        max_age=settings.access_token_expire_hours * 3600,
        samesite="lax",
    )

    return Token(
        access_token=access_token,
        must_change_password=settings.is_default_password,
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout and clear session."""
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )
    response.delete_cookie(key="access_token", secure=is_https, samesite="lax")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(user: dict = Depends(get_current_user)):
    """Get current authenticated user information."""
    return UserInfo(username=user["username"])
