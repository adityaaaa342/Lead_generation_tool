"""Configured HTTP client with robots.txt compliance, rate limiting, and caching."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from leadpilot.config import Settings, get_settings
from leadpilot.storage.cache import HTTPCache
from leadpilot.utils.rate_limiter import DomainRateLimiter
from leadpilot.utils.robots import RobotsChecker

logger = logging.getLogger(__name__)


class FetchResult:
    """Result of an HTTP fetch operation."""

    def __init__(
        self,
        url: str,
        status_code: int,
        text: str,
        headers: dict[str, str],
        from_cache: bool = False,
    ):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self.from_cache = from_cache

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def __repr__(self) -> str:
        return f"FetchResult(url={self.url!r}, status={self.status_code}, cached={self.from_cache})"


class HTTPClient:
    """HTTP client wrapping httpx with robots.txt, rate limiting, and caching."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._cache = HTTPCache(self.settings.cache_dir / "http_cache.db")
        self._robots = RobotsChecker(
            user_agent=self.settings.user_agent,
            http_cache=self._cache,
        )
        self._rate_limiter = DomainRateLimiter(
            default_rps=self.settings.rate_limit_rps,
        )

        # Set known API rate limits
        self._rate_limiter.set_domain_limit("api.github.com", rps=0.015, burst=1)  # ~60/hr
        self._rate_limiter.set_domain_limit("oauth.reddit.com", rps=1.0, burst=2)
        self._rate_limiter.set_domain_limit("overpass-api.de", rps=0.2, burst=1)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=15),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    def _do_fetch(self, url: str, method: str, params: dict | None) -> httpx.Response:
        """Perform the actual HTTP request with retry."""
        if method.upper() == "GET":
            return self._client.get(url, params=params)
        elif method.upper() == "POST":
            return self._client.post(url, json=params)
        else:
            return self._client.request(method, url, params=params)

    def fetch(
        self,
        url: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
        respect_robots: bool = True,
    ) -> FetchResult:
        """Fetch a URL with all guardrails (robots.txt, rate limiting, caching).

        Args:
            url: URL to fetch.
            method: HTTP method.
            params: Query parameters (GET) or JSON body (POST).
            use_cache: Whether to use/populate the cache.
            respect_robots: Whether to check robots.txt.

        Returns:
            FetchResult with status, text, and headers.
        """
        domain = urlparse(url).netloc

        # 1. Check robots.txt
        if respect_robots and not self._robots.can_fetch(url):
            logger.info("Blocked by robots.txt: %s", url)
            return FetchResult(url=url, status_code=403, text="", headers={}, from_cache=False)

        # 2. Check cache
        if use_cache:
            cached = self._cache.get_response(url, method, params)
            if cached is not None:
                logger.debug("HTTP cache hit: %s", url)
                return FetchResult(
                    url=url,
                    status_code=cached["status_code"],
                    text=cached["text"],
                    headers=cached.get("headers", {}),
                    from_cache=True,
                )

        # 3. Rate limit
        self._rate_limiter.wait(url)

        # 4. Use crawl-delay from robots.txt if it's larger
        crawl_delay = self._robots.crawl_delay(url)
        if crawl_delay and crawl_delay > (1.0 / self.settings.rate_limit_rps):
            import time
            logger.debug("Applying crawl-delay of %.1fs for %s", crawl_delay, domain)
            time.sleep(crawl_delay)

        # 5. Fetch
        try:
            response = self._do_fetch(url, method, params)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return FetchResult(url=url, status_code=0, text="", headers={}, from_cache=False)

        result = FetchResult(
            url=url,
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
            from_cache=False,
        )

        # 6. Cache successful responses
        if use_cache and result.ok:
            self._cache.set_response(
                url=url,
                response_data={
                    "status_code": result.status_code,
                    "text": result.text,
                    "headers": dict(response.headers),
                },
                method=method,
                params=params,
                ttl=self.settings.cache_ttl_http,
                domain=domain,
            )

        return result

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
