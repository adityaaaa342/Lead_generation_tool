"""GitHub public API collector for discovering companies/founders."""

from __future__ import annotations

import json
import logging
from typing import Any

from leadpilot.collectors.base import BaseCollector
from leadpilot.models import ICP, RawLead

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubCollector(BaseCollector):
    """Collect leads from GitHub public API — organizations and users."""

    SOURCE_NAME = "github_collector"

    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Search GitHub for organizations and users matching ICP keywords.

        Params can include:
            - queries: explicit search queries
            - search_type: 'orgs', 'users', or 'both' (default: 'both')
        """
        params = params or {}
        leads: list[RawLead] = []

        queries = params.get("queries") or self._build_queries(icp)
        search_type = params.get("search_type", "both")

        for query in queries:
            if len(leads) >= max_leads:
                break

            if search_type in ("orgs", "both"):
                leads.extend(self._search_orgs(query, max_leads - len(leads)))

            if search_type in ("users", "both") and len(leads) < max_leads:
                leads.extend(self._search_users(query, max_leads - len(leads)))

        return leads[:max_leads]

    def _build_queries(self, icp: ICP) -> list[str]:
        """Build GitHub search queries from ICP."""
        queries = []
        for keyword in icp.keywords[:3]:  # Limit queries
            location_filter = ""
            if icp.locations:
                location_filter = f" location:{icp.locations[0]}"
            queries.append(f"{keyword}{location_filter}")
        return queries or ["startup"]

    def _search_orgs(self, query: str, limit: int) -> list[RawLead]:
        """Search GitHub organizations."""
        url = f"{GITHUB_API}/search/users"
        result = self.http.fetch(
            url,
            params={"q": f"{query} type:org", "per_page": min(limit, 30)},
            respect_robots=False,  # API endpoint
        )

        if not result.ok:
            logger.warning("GitHub org search failed (status %d)", result.status_code)
            return []

        try:
            data = json.loads(result.text)
            items = data.get("items", [])
        except (json.JSONDecodeError, KeyError):
            return []

        leads = []
        for item in items[:limit]:
            lead = self._github_user_to_lead(item, is_org=True)
            if lead:
                leads.append(lead)

        return leads

    def _search_users(self, query: str, limit: int) -> list[RawLead]:
        """Search GitHub users (potential founders)."""
        url = f"{GITHUB_API}/search/users"
        result = self.http.fetch(
            url,
            params={"q": f"{query} type:user", "per_page": min(limit, 30)},
            respect_robots=False,
        )

        if not result.ok:
            logger.warning("GitHub user search failed (status %d)", result.status_code)
            return []

        try:
            data = json.loads(result.text)
            items = data.get("items", [])
        except (json.JSONDecodeError, KeyError):
            return []

        leads = []
        for item in items[:limit]:
            # Fetch user profile for more details
            profile = self._fetch_profile(item.get("url", ""))
            lead = self._github_user_to_lead(profile or item, is_org=False)
            if lead:
                leads.append(lead)

        return leads

    def _fetch_profile(self, api_url: str) -> dict | None:
        """Fetch a full GitHub user/org profile."""
        if not api_url:
            return None

        result = self.http.fetch(api_url, respect_robots=False)
        if not result.ok:
            return None

        try:
            return json.loads(result.text)
        except json.JSONDecodeError:
            return None

    def _github_user_to_lead(self, data: dict, is_org: bool) -> RawLead | None:
        """Convert GitHub API user/org data to a RawLead."""
        name = data.get("name") or data.get("login")
        if not name:
            return None

        blog = data.get("blog") or ""
        domain = None
        website_url = None

        if blog:
            if not blog.startswith(("http://", "https://")):
                blog = f"https://{blog}"
            from urllib.parse import urlparse
            parsed = urlparse(blog)
            if parsed.netloc:
                domain = parsed.netloc.lower().removeprefix("www.")
                website_url = blog

        email = data.get("email")
        emails = [email] if email else []

        return self._make_lead(
            company_name=data.get("company", name) if not is_org else name,
            domain=domain,
            website_url=website_url,
            emails=emails,
            description=data.get("bio") or data.get("description"),
            location=data.get("location"),
            source_url=data.get("html_url", f"https://github.com/{data.get('login', '')}"),
            raw_data={
                "github_login": data.get("login"),
                "github_type": "org" if is_org else "user",
                "public_repos": data.get("public_repos"),
                "followers": data.get("followers"),
                "company": data.get("company"),
            },
        )
