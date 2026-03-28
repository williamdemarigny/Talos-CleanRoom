"""OIDC integration module for Keycloak authentication.

Provides functions for the OpenID Connect authorization code flow:
1. Discovery: Fetch Keycloak's well-known configuration
2. Authorization: Build redirect URL to Keycloak login
3. Token exchange: Exchange authorization code for tokens
4. Validation: Validate ID tokens using JWKS
5. Userinfo: Fetch user profile from Keycloak
"""

import base64
import hashlib
import logging
import secrets
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Cache for OIDC discovery document
_oidc_config_cache: dict = {}


async def get_oidc_config(issuer_url: str) -> dict:
    """Fetch and cache the OIDC discovery document (.well-known/openid-configuration)."""
    if issuer_url in _oidc_config_cache:
        return _oidc_config_cache[issuer_url]

    well_known_url = f"{issuer_url}/.well-known/openid-configuration"
    async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
        response = await client.get(well_known_url)
        response.raise_for_status()
        config = response.json()

    _oidc_config_cache[issuer_url] = config
    return config


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(43)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


async def build_authorization_url(
    settings,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """Build the Keycloak authorization endpoint URL for redirect.

    Args:
        settings: App settings with oidc_* fields
        redirect_uri: Callback URL (built by the router from the request)
        state: CSRF protection state parameter
        nonce: Nonce for ID token validation
        code_challenge: PKCE S256 code challenge

    Returns:
        Full authorization URL to redirect the user to.
    """
    config = await get_oidc_config(settings.oidc_issuer_url)
    auth_endpoint = config["authorization_endpoint"]

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    return f"{auth_endpoint}?{urlencode(params)}"


async def exchange_code_for_tokens(
    settings,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> Optional[dict]:
    """Exchange an authorization code for tokens at the Keycloak token endpoint.

    Args:
        settings: App settings with oidc_* fields
        code: Authorization code from callback
        code_verifier: PKCE code verifier
        redirect_uri: Must match the redirect_uri used in authorization request

    Returns:
        Token response dict with access_token, id_token, refresh_token, etc.
        Returns None on failure.
    """
    config = await get_oidc_config(settings.oidc_issuer_url)
    token_endpoint = config["token_endpoint"]

    data = {
        "grant_type": "authorization_code",
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
        response = await client.post(token_endpoint, data=data)
        if response.status_code != 200:
            logger.error("Token exchange failed: %s %s", response.status_code, response.text)
            return None
        return response.json()


async def get_end_session_url(
    settings,
    post_logout_redirect_uri: str,
    id_token_hint: str = None,
) -> str:
    """Build the Keycloak end-session (logout) URL.

    Args:
        settings: App settings with oidc_* fields
        post_logout_redirect_uri: Where to redirect after logout
        id_token_hint: Optional ID token for session identification

    Returns:
        Logout URL to redirect the user to.
    """
    config = await get_oidc_config(settings.oidc_issuer_url)
    logout_endpoint = config.get("end_session_endpoint", "")

    params = {"post_logout_redirect_uri": post_logout_redirect_uri}
    if id_token_hint:
        params["id_token_hint"] = id_token_hint

    return f"{logout_endpoint}?{urlencode(params)}"
