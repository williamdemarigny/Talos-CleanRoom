"""Security middleware: CSP headers with nonce support, HSTS, X-Frame-Options.

Generates a per-request CSP nonce and stores it on ``request.state.csp_nonce``
so Jinja2 templates can use ``{{ request.state.csp_nonce }}`` in ``<script>``
tags to satisfy the nonce-based CSP policy.

To use in templates::

    <script nonce="{{ request.state.csp_nonce }}">
        // inline JavaScript
    </script>

Alpine.js CSP build (``alpinejs/csp``) should be used instead of the
default Alpine build to avoid the need for ``unsafe-eval``.
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CDN origins used by the frontend (Tailwind CSS, Alpine.js)
SCRIPT_ORIGINS = "https://cdn.tailwindcss.com https://unpkg.com"
STYLE_ORIGINS = "https://cdn.tailwindcss.com"


def _build_csp(nonce: str) -> str:
    """Build CSP header with a per-request nonce."""
    return (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' {SCRIPT_ORIGINS}; "
        f"style-src 'self' 'unsafe-inline' {STYLE_ORIGINS}; "
        f"img-src 'self' data:; "
        f"connect-src 'self' wss: ws:; "
        f"font-src 'self'; "
        f"frame-ancestors 'none'"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses with per-request CSP nonce."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate a cryptographically random nonce for this request
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _build_csp(nonce)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response
