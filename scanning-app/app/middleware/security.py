"""Security middleware: CSP headers, HSTS, X-Frame-Options."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CDN origins used by the frontend (Tailwind CSS, Alpine.js)
SCRIPT_ORIGINS = "https://cdn.tailwindcss.com https://unpkg.com"
STYLE_ORIGINS = "https://cdn.tailwindcss.com"

CSP_POLICY = (
    f"default-src 'self'; "
    f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {SCRIPT_ORIGINS}; "
    f"style-src 'self' 'unsafe-inline' {STYLE_ORIGINS}; "
    f"img-src 'self' data:; "
    f"connect-src 'self' wss: ws:; "
    f"font-src 'self'; "
    f"frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP_POLICY
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response
