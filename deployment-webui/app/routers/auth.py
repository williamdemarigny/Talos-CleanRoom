"""Authentication API router."""

from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.config import get_settings, Settings
from app.auth import authenticate_user, create_access_token, get_current_user

router = APIRouter()


class Token(BaseModel):
    """Token response model."""
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class UserInfo(BaseModel):
    """User information response."""
    username: str


@router.post("/login", response_model=Token)
async def login(
    response: Response,
    form_data: LoginRequest,
    settings: Settings = Depends(get_settings)
):
    """Authenticate user and return JWT token."""
    if not authenticate_user(form_data.username, form_data.password, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(form_data.username, settings)

    # Also set cookie for browser-based access
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.access_token_expire_hours * 3600,
        samesite="lax"
    )

    return Token(access_token=access_token)


@router.post("/logout")
async def logout(response: Response):
    """Logout and clear session."""
    response.delete_cookie(key="access_token")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(user: dict = Depends(get_current_user)):
    """Get current authenticated user information."""
    return UserInfo(username=user["username"])
