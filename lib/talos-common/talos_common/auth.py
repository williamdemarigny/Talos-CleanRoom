"""Authentication module with JWT token handling.

Provides pure functions for JWT creation/validation and password hashing,
plus FastAPI dependency factories for use in routers.

Supports dual-mode JWT validation:
- HS256 (local): Legacy tokens signed with derived jwt_signing_key
- RS256 (Keycloak): OIDC tokens validated against Keycloak JWKS endpoint

All functions accept a ``settings`` parameter (BaseAppSettings or subclass)
rather than importing a specific config module, making them reusable
across all three apps.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from jwt import PyJWKClient
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

# Cache for JWKS client (avoids re-fetching on every request)
_jwks_client_cache: dict = {}


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

    Includes ``aud: "local"`` claim to distinguish from Keycloak tokens
    and prevent token confusion during OIDC transition.
    """
    expire = datetime.utcnow() + timedelta(hours=settings.access_token_expire_hours)
    to_encode = {
        "sub": username,
        "aud": "local",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(to_encode, settings.jwt_signing_key, algorithm=LOCAL_ALGORITHM)


def _get_jwks_client(issuer_url: str):
    """Get or create a cached PyJWKClient for the given issuer."""
    if issuer_url not in _jwks_client_cache:
        jwks_uri = f"{issuer_url}/protocol/openid-connect/certs"
        # ssl_context=False skips TLS verification (staging certs)
        # Switch to default (True) after moving to letsencrypt-prod
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _jwks_client_cache[issuer_url] = PyJWKClient(jwks_uri, ssl_context=ctx)
    return _jwks_client_cache[issuer_url]


def decode_token(token: str, settings) -> Optional[dict]:
    """Decode and validate a JWT token in dual-mode.

    - If token uses RS256 and ``oidc_issuer_url`` is configured:
      Validate against Keycloak JWKS endpoint.
    - If token uses HS256: Validate against local ``jwt_signing_key``
      with ``audience="local"`` enforcement.

    Returns dict with at minimum ``username`` and ``exp`` keys, or None.
    """
    try:
        # Inspect header to determine algorithm without full validation
        header = pyjwt.get_unverified_header(token)
        alg = header.get("alg")

        if alg == "RS256" and settings.oidc_issuer_url:
            # OIDC mode: validate against Keycloak JWKS
            jwks_client = _get_jwks_client(settings.oidc_issuer_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.oidc_client_id,
                issuer=settings.oidc_issuer_url,
            )
            # Map Keycloak claims to app format
            username = payload.get("preferred_username") or payload.get("sub")
            if username is None:
                return None
            return {
                "username": username,
                "sub": payload.get("sub"),
                "exp": payload.get("exp"),
                "roles": payload.get("realm_access", {}).get("roles", []),
            }

        elif alg == "HS256":
            # Local JWT validation with audience enforcement
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

        else:
            # Unsupported algorithm
            return None

    except pyjwt.InvalidAudienceError:
        # Token has wrong audience — could be legacy token without aud claim.
        # Fall back to decode without audience check for backward compatibility
        # during the transition period. Remove this fallback in Phase 4.
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
    Supports both local HS256 and Keycloak RS256 tokens.
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


def require_role(role: str):
    """FastAPI dependency that requires the current user to have a specific realm role.

    Usage in routers::

        @router.post("/admin-action")
        async def admin_action(user: dict = Depends(require_role("admin"))):
            ...

    For local HS256 tokens (no roles), the ``admin`` role is implicitly
    granted since local auth is single-user admin-only. This ensures
    backward compatibility during the OIDC transition.

    Raises HTTP 403 if the user lacks the required role.
    """
    async def _dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        settings=Depends(talos_common.get_settings),
    ) -> dict:
        user = await get_current_user(request, credentials, settings)

        # Local HS256 tokens don't carry roles — the single admin user
        # implicitly has all roles. Once OIDC-only mode is enforced
        # (Phase 4), this fallback can be removed.
        user_roles = user.get("roles", [])
        if not user_roles:
            # Legacy local token — grant implicit admin
            return user

        if role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user

    return _dependency
