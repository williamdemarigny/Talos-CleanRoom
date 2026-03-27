"""OIDC flow state management using Fernet-encrypted cookies.

Stores the OIDC authorization request state (nonce, PKCE code_verifier,
state parameter) in a Fernet-encrypted cookie. This avoids the need for
server-side session storage (Redis, database) while remaining secure.

Uses the existing ``fernet_key`` derived from SECRET_KEY in config_base.py.
Encrypted payload is ~220 bytes — well within the 4KB cookie limit.
"""

import json
import time
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class OIDCStateManager:
    """Manages OIDC flow state via Fernet-encrypted cookies."""

    # State is valid for 10 minutes (typical OIDC callback window)
    STATE_TTL_SECONDS = 600

    def __init__(self, fernet_key: bytes):
        self.cipher = Fernet(fernet_key)

    def encrypt_state(
        self,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> str:
        """Encrypt OIDC flow state into a cookie-safe string.

        Args:
            state: CSRF protection state parameter
            nonce: Nonce for ID token validation
            code_verifier: PKCE code verifier

        Returns:
            URL-safe base64-encoded encrypted string.
        """
        payload = json.dumps({
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "created_at": time.time(),
        })
        return self.cipher.encrypt(payload.encode()).decode()

    def decrypt_state(self, token: str) -> Optional[dict]:
        """Decrypt and validate OIDC flow state from a cookie.

        Args:
            token: Encrypted state string from cookie

        Returns:
            Dict with state, nonce, code_verifier keys, or None if
            invalid/expired.
        """
        try:
            payload = json.loads(self.cipher.decrypt(token.encode()))

            # Check TTL
            created_at = payload.get("created_at", 0)
            if time.time() - created_at > self.STATE_TTL_SECONDS:
                return None

            return payload
        except (InvalidToken, json.JSONDecodeError, TypeError):
            return None
