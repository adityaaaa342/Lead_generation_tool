"""robots.txt parser and compliance checker."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from leadpilot.storage.cache import HTTPCache

logger = logging.getLogger(__name__)


class RobotsChecker:
    """Check URL fetchability against robots.txt with caching."""

    def __init__(self, user_agent: str, http_cache: HTTPCache | None = None):
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._cache = http_cache

    def _get_robots_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _get_parser(self, url: str) -> RobotFileParser | None:
        """Get or create a RobotFileParser for the given URL's domain."""
        robots_url = self._get_robots_url(url)

        if robots_url in self._parsers:
            return self._parsers[robots_url]

        parser = RobotFileParser()
        parser.set_url(robots_url)

        try:
            parser.read()
            self._parsers[robots_url] = parser
            logger.debug("Loaded robots.txt from %s", robots_url)
        except Exception as exc:
            logger.debug("Could not fetch robots.txt from %s: %s", robots_url, exc)
            # If robots.txt is unavailable, allow everything
            self._parsers[robots_url] = None

        return self._parsers[robots_url]

    def can_fetch(self, url: str) -> bool:
        """Check if the given URL is allowed by robots.txt."""
        parser = self._get_parser(url)
        if parser is None:
            return True  # No robots.txt = everything allowed
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True  # On error, allow

    def crawl_delay(self, url: str) -> float | None:
        """Get the crawl-delay for the user agent, if specified."""
        parser = self._get_parser(url)
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None
