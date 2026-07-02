"""Token bucket rate limiter per platform.

Each platform has its own token bucket with configurable rate.
Used by fetch_and_land to respect platform API rate limits.
Implements 3 layers of rate limiting:
  1. Celery task-level rate_limit decorator
  2. Token bucket per platform (this module)
  3. Exponential backoff + jitter on HTTP 429 (in the adapter)
"""

import asyncio
import time

from app.infra.settings import settings


class TokenBucket:
    """Simple async token bucket rate limiter.

    Tokens refill at a constant rate up to a maximum burst.
    If no tokens are available, the caller must wait.
    """

    def __init__(self, rate_per_minute: int, burst: int | None = None):
        """
        Args:
            rate_per_minute: Number of requests allowed per minute
            burst: Max tokens that can accumulate (default: rate_per_minute)
        """
        self._rate = rate_per_minute / 60.0  # tokens per second
        self._burst = burst or rate_per_minute
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Wait until a token is available, then acquire it.

        Returns:
            Time spent waiting (0 if token was immediately available).
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0

            # Calculate how long to wait for 1 token
            wait_time = (1.0 - self._tokens) / self._rate
            self._tokens = 0.0
            self._last_refill += wait_time

        await asyncio.sleep(wait_time)
        return wait_time


# Pre-configured buckets per platform (lazily initialized on first call)
_buckets: dict[str, TokenBucket] = {}


def get_bucket(platform_code: str) -> TokenBucket:
    """Return the token bucket for a given platform, creating it if needed.

    Rates are read from settings:
      - RATE_LIMIT_FACEBOOK_PER_MIN (default 200)
      - RATE_LIMIT_TIKTOK_PER_MIN (default 100)
      - RATE_LIMIT_GOOGLE_PER_MIN (default 150)
    """
    global _buckets
    code = platform_code.upper()
    if code not in _buckets:
        rate = {
            "FACEBOOK": settings.rate_limit_facebook_per_min,
            "TIKTOK": settings.rate_limit_tiktok_per_min,
            "GOOGLE": settings.rate_limit_google_per_min,
        }.get(code, 60)  # Default: 60 req/min for unknown platforms
        _buckets[code] = TokenBucket(rate_per_minute=rate)
    return _buckets[code]