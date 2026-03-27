"""Base application settings shared across all Talos CleanRoom apps.

Each app inherits from ``BaseAppSettings`` and adds its own fields:
- DeploymentSettings adds: repo_root, master_node, node_ips, dependencies
- ScanningSettings adds: database_url, faraday_sync_enabled
- PortalSettings adds: deployment_console_url, scanning_console_url
"""

import base64
import hashlib
import hmac

from pydantic_settings import BaseSettings


class BaseAppSettings(BaseSettings):
    """Authentication and cryptographic settings shared by all apps.

    A single ``secret_key`` env var is shared across all three apps, but
    each cryptographic purpose uses a **derived key** via HMAC-SHA256
    with a distinct context string.  Compromising one derived key does
    not expose the others.
    """

    secret_key: str = "change-me-in-production"
    admin_username: str = "admin"
    admin_password_hash: str = (
        "$2b$12$Fosg.8JShshDJrpDuu2/T.9gzo05L2RJ.n1n5rQM35a7AN2NK555e"
    )  # Default: admin
    access_token_expire_hours: int = 8

    # OIDC configuration (optional; empty = disabled, falls back to local JWT)
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_path: str = "/auth/callback"
    oidc_scopes: str = "openid profile email"

    # Known default hash — used to detect first-login and prompt password change
    _DEFAULT_PASSWORD_HASH: str = (
        "$2b$12$Fosg.8JShshDJrpDuu2/T.9gzo05L2RJ.n1n5rQM35a7AN2NK555e"
    )

    @property
    def is_default_password(self) -> bool:
        """Return True if the admin password hash is still the default."""
        return self.admin_password_hash == self._DEFAULT_PASSWORD_HASH

    @property
    def jwt_signing_key(self) -> str:
        """Derived key for JWT signing (HMAC-SHA256 of secret_key + context)."""
        return hmac.new(
            self.secret_key.encode(), b"jwt-signing", hashlib.sha256
        ).hexdigest()

    @property
    def code_exchange_key(self) -> str:
        """Derived key for one-time code HMAC (separate from JWT key)."""
        return hmac.new(
            self.secret_key.encode(), b"code-exchange", hashlib.sha256
        ).hexdigest()

    @property
    def fernet_key(self) -> bytes:
        """Derived key for Fernet state encryption (separate from JWT key)."""
        key_bytes = hmac.new(
            self.secret_key.encode(), b"fernet-state", hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(key_bytes)
