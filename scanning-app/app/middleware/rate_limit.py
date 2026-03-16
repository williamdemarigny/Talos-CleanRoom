"""In-memory token-bucket rate limiter.

Accepted risk: counters reset on pod restart (see Appendix H).
Upgrade path: swap TokenBucket store for Redis when needed.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Rate limit rules: (path_prefix, key_type, max_tokens, refill_per_second)
RATE_LIMITS: list[tuple[str, str, int, float]] = [
    ("/api/auth/login", "ip", 5, 5 / 60),        # 5 per minute per IP
    ("/api/scan/start", "user", 10, 10 / 60),     # 10 per minute per user
    ("/api/ioc-scan/start", "user", 10, 10 / 60), # 10 per minute per user
    ("/api/export/", "user", 20, 20 / 60),         # 20 per minute per user
]


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by IP or authenticated user."""

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=0)
        )

    def _get_key(self, request: Request, key_type: str) -> str:
        if key_type == "user":
            # Best-effort: extract username from JWT in cookie or header
            token = request.cookies.get("access_token")
            if not token:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth[7:]
            if token:
                # Decode just the sub claim without verification (rate limit is best-effort)
                import base64, json
                try:
                    payload_b64 = token.split(".")[1]
                    payload_b64 += "=" * (-len(payload_b64) % 4)
                    payload = json.loads(base64.b64decode(payload_b64))
                    return f"user:{payload.get('sub', 'unknown')}"
                except Exception:
                    pass
            # Fall back to IP if user can't be determined
            return f"ip:{request.client.host if request.client else 'unknown'}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def _check_rate(self, key: str, max_tokens: float, refill_rate: float) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        now = time.monotonic()
        bucket = self._buckets[key]
        # Initialize new buckets at max capacity
        if bucket.tokens == 0 and bucket.last_refill == 0:
            bucket.tokens = max_tokens
            bucket.last_refill = now

        # Refill tokens
        elapsed = now - bucket.last_refill
        bucket.tokens = min(max_tokens, bucket.tokens + elapsed * refill_rate)
        bucket.last_refill = now

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True
        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        for path_prefix, key_type, max_tokens, refill_rate in RATE_LIMITS:
            if path.startswith(path_prefix) and request.method == "POST":
                key = self._get_key(request, key_type)
                rate_key = f"{path_prefix}:{key}"
                if not self._check_rate(rate_key, max_tokens, refill_rate):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded. Try again later."},
                    )
                break

        return await call_next(request)
