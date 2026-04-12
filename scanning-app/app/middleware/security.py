"""Security middleware: CSP headers, HSTS, X-Frame-Options.

Applies a practical Content-Security-Policy that works with the standard
Alpine.js CDN build (which requires ``unsafe-eval`` for directive
expressions like ``x-show``, ``:class``, ``x-text``, etc.) and inline
scripts (login page, ``onclick`` handlers).

The CSP still prevents:
- Loading scripts from unauthorized origins
- Framing the app (clickjacking via ``frame-ancestors 'none'``)
- Loading resources from unauthorized origins
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CDN origins used by the frontend (Tailwind CSS, Alpine.js)
SCRIPT_ORIGINS = "https://cdn.tailwindcss.com https://unpkg.com"
STYLE_ORIGINS = "https://cdn.tailwindcss.com"

CSP = (
    "default-src 'self'; "
    f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {SCRIPT_ORIGINS}; "
    f"style-src 'self' 'unsafe-inline' {STYLE_ORIGINS}; "
    "img-src 'self' data:; "
    "connect-src 'self' wss: ws:; "
    "font-src 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response
