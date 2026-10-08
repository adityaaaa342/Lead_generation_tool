"""Reddit public API collector for finding startup/business leads."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from leadpilot.collectors.base import BaseCollector
from leadpilot.models import ICP, RawLead

logger = logging.getLogger(__name__)

# Subreddits relevant to startups and business
DEFAULT_SUBREDDITS = [
    "startups", "Entrepreneur", "SaaS", "indiehackers",
    "smallbusiness", "venturecapital", "IndiaStartups",
]


class RedditCollector(BaseCollector):
    """Collect leads from Reddit public JSON API (no auth needed)."""

    SOURCE_NAME = "reddit_collector"

    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Search Reddit for posts mentioning companies matching the ICP.

        Params can include:
            - subreddits: list of subreddit names
            - queries: explicit search terms
        """
        params = params or {}
        leads: list[RawLead] = []

        subreddits = params.get("subreddits", DEFAULT_SUBREDDITS)
        queries = params.get("queries") or icp.keywords[:3]

        for subreddit in subreddits:
            if len(leads) >= max_leads:
                break

            for query in queries:
                if len(leads) >= max_leads:
                    break

                sub_leads = self._search_subreddit(subreddit, query, max_leads - len(leads))
                leads.extend(sub_leads)

        return leads[:max_leads]

    def _search_subreddit(
        self, subreddit: str, query: str, limit: int
    ) -> list[RawLead]:
        """Search a subreddit for posts containing company mentions."""
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        result = self.http.fetch(
            url,
            params={
                "q": query,
                "restrict_sr": "on",
                "sort": "relevance",
                "t": "year",
                "limit": min(limit * 2, 25),  # Fetch more since not all will have leads
            },
        )

        if not result.ok:
            logger.warning(
                "Reddit search failed for r/%s (status %d)", subreddit, result.status_code
            )
            return []

        try:
            data = json.loads(result.text)
            posts = data.get("data", {}).get("children", [])
        except (json.JSONDecodeError, KeyError):
            return []

        leads: list[RawLead] = []
        seen_domains: set[str] = set()

        for post in posts:
            post_data = post.get("data", {})
            extracted = self._extract_leads_from_post(post_data)

            for lead in extracted:
                if lead.domain and lead.domain in seen_domains:
                    continue
                if lead.domain:
                    seen_domains.add(lead.domain)
                leads.append(lead)

                if len(leads) >= limit:
                    break

        return leads

    def _extract_leads_from_post(self, post_data: dict) -> list[RawLead]:
        """Extract potential company leads from a Reddit post."""
        leads: list[RawLead] = []
        title = post_data.get("title", "")
        selftext = post_data.get("selftext", "")
        url = post_data.get("url", "")
        permalink = f"https://www.reddit.com{post_data.get('permalink', '')}"

        # Check if the post URL is a company website (not reddit/imgur/etc.)
        if url and not self._is_social_or_media_url(url):
            parsed = urlparse(url)
            if parsed.netloc:
                domain = parsed.netloc.lower().removeprefix("www.")
                company_name = self._guess_company_name(title, domain)

                leads.append(self._make_lead(
                    company_name=company_name,
                    domain=domain,
                    website_url=url,
                    description=title,
                    source_url=permalink,
                    raw_data={
                        "reddit_title": title,
                        "reddit_score": post_data.get("score", 0),
                        "reddit_subreddit": post_data.get("subreddit"),
                        "selftext_preview": selftext[:300],
                    },
                ))

        # Extract URLs from post text
        urls_in_text = re.findall(r'https?://[^\s\)]+', selftext)
        for found_url in urls_in_text[:3]:  # Limit
            if self._is_social_or_media_url(found_url):
                continue
            parsed = urlparse(found_url)
            if parsed.netloc:
                domain = parsed.netloc.lower().removeprefix("www.")
                leads.append(self._make_lead(
                    company_name=domain.split(".")[0].title(),
                    domain=domain,
                    website_url=found_url,
                    description=title,
                    source_url=permalink,
                    raw_data={
                        "reddit_title": title,
                        "extracted_from": "selftext",
                    },
                ))

        return leads

    @staticmethod
    def _guess_company_name(title: str, domain: str) -> str:
        """Try to extract a company name from the title, fall back to domain."""
        # Simple heuristic: use domain name
        return domain.split(".")[0].replace("-", " ").title()

    @staticmethod
    def _is_social_or_media_url(url: str) -> bool:
        """Check if URL is a social media or media hosting site."""
        skip_domains = {
            "reddit.com", "imgur.com", "i.redd.it", "youtube.com",
            "youtu.be", "twitter.com", "x.com", "facebook.com",
            "instagram.com", "tiktok.com", "gfycat.com", "giphy.com",
            "wikipedia.org", "google.com",
        }
        parsed = urlparse(url)
        return any(d in parsed.netloc for d in skip_domains)
