"""Abstract base class for all lead collectors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from leadpilot.config import Settings, get_settings
from leadpilot.models import ICP, RawLead
from leadpilot.utils.http import HTTPClient

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Common interface for all lead collectors.

    Every collector must:
    1. Implement collect(icp, params, max_leads) -> list[RawLead]
    2. Obey robots.txt (handled by HTTPClient)
    3. Rate-limit itself (handled by HTTPClient)
    4. Cache responses (handled by HTTPClient)
    5. Set a clear User-Agent (handled by HTTPClient)
    """

    SOURCE_NAME: str = "base"

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: HTTPClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.http = http_client or HTTPClient(self.settings)

    @abstractmethod
    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Collect raw leads matching the ICP.

        Args:
            icp: The ideal customer profile.
            params: Source-specific parameters from the collection plan.
            max_leads: Maximum number of leads to return.

        Returns:
            A list of RawLead objects.
        """
        ...

    def _make_lead(self, **kwargs) -> RawLead:
        """Helper to create a RawLead with source_name pre-filled."""
        return RawLead(source_name=self.SOURCE_NAME, **kwargs)
