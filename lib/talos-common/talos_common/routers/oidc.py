"""OIDC authentication router for Keycloak integration.

Provides endpoints for the OpenID Connect authorization code flow:
- GET /auth/login — Redirects to Keycloak login page
- GET /auth/callback — Handles the OIDC callback after Keycloak login
- GET /auth/logout — Redirects to Keycloak logout endpoint

These endpoints are only active when ``oidc_issuer_url`` is configured
in the application settings. When OIDC is disabled, the existing local
JWT login flow (POST /api/auth/login) remains the primary auth method.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

import talos_common
from talos_common.oidc import (
    build_authorization_url,
    exchange_code_for_tokens,
    generate_pkce_pair,
    get_end_session_url,
)
from talos_common.oidc_state import OIDCStateManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OIDC"])

# Cookie name for OIDC flow state (separate from access_token cookie).
# Uses __Secure- prefix which requires Secure flag but is less strict
# than __Host- (which also requires Path=/ and no Domain attribute).
OIDC_STATE_COOKIE = "__Secure-oidc_state"


def _build_callback_uri(request: Request) -> str:
    """Build the OIDC callback URI from the current request.

    Uses the request's host and scheme (respecting X-Forwarded-* headers
    from Traefik) to construct the callback URL. This avoids needing a
    separate oidc_redirect_host config field per app.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.hostname)
    port = request.url.port
    # Don't include port for standard HTTPS
    if port and port != 443 and scheme == "https":
        return f"{scheme}://{host}:{port}/auth/callback"
    return f"{scheme}://{host}/auth/callback"


@router.get("/auth/login")
async def oidc_login(
    request: Request,
    settings=Depends(talos_common.get_settings),
):
    """Redirect user to Keycloak authorization endpoint.

    Generates PKCE code verifier/challenge and CSRF state parameter,
    stores them in an encrypted cookie, and redirects to Keycloak.
    """
    if not settings.oidc_issuer_url:
        return RedirectResponse(url="/login", status_code=302)

    try:
        # Generate PKCE pair and state/nonce
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)

        # Encrypt state into cookie
        state_mgr = OIDCStateManager(settings.fernet_key)
        encrypted_state = state_mgr.encrypt_state(state, nonce, code_verifier)

        # Build callback URI from request
        callback_uri = _build_callback_uri(request)

        # Build authorization URL
        auth_url = await build_authorization_url(
            settings, callback_uri, state, nonce, code_challenge,
        )

        # Set encrypted state cookie and redirect
        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            key=OIDC_STATE_COOKIE,
            value=encrypted_state,
            max_age=600,  # 10 minutes
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response

    except Exception:
        logger.exception("Failed to initiate OIDC login")
        return RedirectResponse(url="/login?error=oidc_unavailable", status_code=302)


@router.get("/auth/callback")
async def oidc_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    settings=Depends(talos_common.get_settings),
):
    """Handle the OIDC callback from Keycloak.

    Validates the state parameter, exchanges the authorization code
    for tokens, and sets the access_token and id_token cookies.
    """
    if not settings.oidc_issuer_url:
        return RedirectResponse(url="/login", status_code=302)

    # Handle Keycloak errors
    if error:
        logger.error("OIDC error: %s — %s", error, error_description)
        return RedirectResponse(url="/login?error=oidc_failed", status_code=302)

    if not code or not state:
        return RedirectResponse(url="/login?error=missing_params", status_code=302)

    # Decrypt and validate state from cookie
    encrypted_state = request.cookies.get(OIDC_STATE_COOKIE)
    if not encrypted_state:
        logger.warning("OIDC callback missing state cookie")
        return RedirectResponse(url="/login?error=state_missing", status_code=302)

    state_mgr = OIDCStateManager(settings.fernet_key)
    saved_state = state_mgr.decrypt_state(encrypted_state)
    if not saved_state:
        logger.warning("OIDC callback: invalid or expired state cookie")
        return RedirectResponse(url="/login?error=state_expired", status_code=302)

    # Verify state parameter matches (CSRF protection)
    if state != saved_state.get("state"):
        logger.warning("OIDC callback: state mismatch")
        return RedirectResponse(url="/login?error=state_mismatch", status_code=302)

    # Build redirect URI (must match what was sent in authorization request)
    redirect_uri = _build_callback_uri(request)

    # Exchange authorization code for tokens
    try:
        tokens = await exchange_code_for_tokens(
            settings,
            code=code,
            code_verifier=saved_state["code_verifier"],
            redirect_uri=redirect_uri,
        )
    except Exception:
        logger.exception("OIDC token exchange raised an exception")
        tokens = None

    if not tokens or "access_token" not in tokens:
        logger.error("OIDC token exchange failed")
        return RedirectResponse(url="/login?error=token_exchange", status_code=302)

    # Determine HTTPS for secure cookies
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )

    # Set access token cookie and redirect to home
    access_token = tokens["access_token"]
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=settings.access_token_expire_hours * 3600,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )

    # Store ID token for single-logout support (Keycloak end_session_endpoint)
    if "id_token" in tokens:
        response.set_cookie(
            key="id_token",
            value=tokens["id_token"],
            max_age=settings.access_token_expire_hours * 3600,
            httponly=True,
            secure=is_https,
            samesite="lax",
            path="/",
        )

    # Clear the OIDC state cookie
    response.delete_cookie(key=OIDC_STATE_COOKIE, secure=True, samesite="lax", path="/")
    return response


@router.get("/auth/logout")
async def oidc_logout(
    request: Request,
    settings=Depends(talos_common.get_settings),
):
    """Log out from Keycloak and clear local session.

    Redirects to Keycloak end-session endpoint to terminate the SSO session,
    then Keycloak redirects back to the login page.
    """
    if not settings.oidc_issuer_url:
        # OIDC not configured — clear cookies and redirect to local login
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie(key="access_token")
        return response

    # Build post-logout redirect URI (login page of this app)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.hostname)
    post_logout_uri = f"{scheme}://{host}/login"

    # Get the ID token hint if available (for single logout)
    id_token_hint = request.cookies.get("id_token")

    # Build logout URL
    logout_url = await get_end_session_url(settings, post_logout_uri, id_token_hint)

    # Clear local cookies and redirect to Keycloak logout
    response = RedirectResponse(url=logout_url, status_code=302)
    response.delete_cookie(key="access_token", secure=True, samesite="lax", path="/")
    response.delete_cookie(key="id_token", secure=True, samesite="lax", path="/")
    response.delete_cookie(key=OIDC_STATE_COOKIE, secure=True, samesite="lax", path="/")
    return response
