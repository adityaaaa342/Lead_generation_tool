"""Per-domain token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class TokenBucket:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate: float = 1.0, burst: int = 3):
        """
        Args:
            rate: Tokens added per second.
            burst: Maximum tokens (bucket size).
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self) -> float:
        """Try to acquire a token. Returns wait time in seconds (0 = immediate)."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        # Calculate how long to wait for the next token
        wait = (1.0 - self._tokens) / self.rate
        return wait

    def wait(self) -> None:
        """Block until a token is available (synchronous)."""
        delay = self.acquire()
        if delay > 0:
            time.sleep(delay)
            self._refill()
            self._tokens -= 1.0

    async def async_wait(self) -> None:
        """Wait until a token is available (async)."""
        delay = self.acquire()
        if delay > 0:
            await asyncio.sleep(delay)
            self._refill()
            self._tokens -= 1.0


class DomainRateLimiter:
    """Manages per-domain rate limiters."""

    def __init__(self, default_rps: float = 1.0, default_burst: int = 3):
        self.default_rps = default_rps
        self.default_burst = default_burst
        self._buckets: dict[str, TokenBucket] = {}
        self._overrides: dict[str, tuple[float, int]] = {}

    def set_domain_limit(self, domain: str, rps: float, burst: int = 3) -> None:
        """Override rate limit for a specific domain."""
        self._overrides[domain] = (rps, burst)
        # Reset bucket if it already exists
        if domain in self._buckets:
            del self._buckets[domain]

    def _get_bucket(self, domain: str) -> TokenBucket:
        if domain not in self._buckets:
            rps, burst = self._overrides.get(
                domain, (self.default_rps, self.default_burst)
            )
            self._buckets[domain] = TokenBucket(rate=rps, burst=burst)
        return self._buckets[domain]

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from a URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]

    def wait(self, url: str) -> None:
        """Block until we can make a request to this URL's domain."""
        domain = self.extract_domain(url)
        bucket = self._get_bucket(domain)
        bucket.wait()
        logger.debug("Rate limiter: acquired token for %s", domain)

    async def async_wait(self, url: str) -> None:
        """Async wait until we can make a request to this URL's domain."""
        domain = self.extract_domain(url)
        bucket = self._get_bucket(domain)
        await bucket.async_wait()
