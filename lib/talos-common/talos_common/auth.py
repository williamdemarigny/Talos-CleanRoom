"""Authentication module with JWT token handling.

Provides pure functions for JWT creation/validation and password hashing,
plus FastAPI dependency factories for use in routers.

All functions accept a ``settings`` parameter (BaseAppSettings or subclass)
rather than importing a specific config module, making them reusable
across all three apps.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext

import talos_common

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Bearer scheme
security = HTTPBearer(auto_error=False)

# Local JWT settings
LOCAL_ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(username: str, settings) -> str:
    """Create a local HS256 JWT access token.

    Uses derived ``jwt_signing_key`` (HMAC-SHA256 of secret_key with
    context "jwt-signing") to limit blast radius if the raw key leaks.
    """
    expire = datetime.utcnow() + timedelta(hours=settings.access_token_expire_hours)
    to_encode = {
        "sub": username,
        "aud": "local",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(to_encode, settings.jwt_signing_key, algorithm=LOCAL_ALGORITHM)


def decode_token(token: str, settings) -> Optional[dict]:
    """Decode and validate a local HS256 JWT token.

    Returns dict with ``username`` and ``exp`` keys, or None.
    """
    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
            audience="local",
        )
        username: str = payload.get("sub")
        if username is None:
            return None
        return {"username": username, "exp": payload.get("exp")}

    except pyjwt.InvalidAudienceError:
        # Fall back to decode without audience check for backward compatibility
        # with tokens issued before the aud claim was added.
        try:
            payload = pyjwt.decode(
                token,
                settings.jwt_signing_key,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            username = payload.get("sub")
            if username is None:
                return None
            return {"username": username, "exp": payload.get("exp")}
        except Exception:
            return None

    except Exception:
        return None


def authenticate_user(username: str, password: str, settings) -> bool:
    """Authenticate a user with username and password."""
    if username != settings.admin_username:
        return False
    return verify_password(password, settings.admin_password_hash)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings=Depends(talos_common.get_settings),
) -> dict:
    """Get current authenticated user from JWT token.

    Checks Authorization header first, then falls back to access_token cookie.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise credentials_exception

    user = decode_token(token, settings)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings=Depends(talos_common.get_settings),
) -> Optional[dict]:
    """Get current user if authenticated, None otherwise."""
    try:
        return await get_current_user(request, credentials, settings)
    except HTTPException:
        return None
