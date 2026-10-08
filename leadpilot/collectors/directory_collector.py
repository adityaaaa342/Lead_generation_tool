"""Directory / incubator member page collector (TiE-style startup directories)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from leadpilot.collectors.base import BaseCollector
from leadpilot.models import ICP, RawLead

logger = logging.getLogger(__name__)

# Default directory URLs to scan — startup/founder ecosystems
DEFAULT_DIRECTORY_URLS = [
    "https://tie.org/tie-charter-members/",
    "https://tie.org/tie-global-chapters/",
    "https://www.startupindia.gov.in/content/sih/en/search.html?roles=Startup&page=0&q=",
    "https://nasscom.in/knowledge-center/publications",
]


class DirectoryCollector(BaseCollector):
    """Collect leads from startup directory and incubator member pages."""

    SOURCE_NAME = "directory_collector"

    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Scrape directory pages for company leads.

        Params can include:
            - urls: list of directory URLs to scrape
            - keywords: override keywords for filtering
        """
        params = params or {}
        urls = params.get("urls", DEFAULT_DIRECTORY_URLS)
        keywords = params.get("keywords", icp.keywords)

        leads: list[RawLead] = []

        for url in urls:
            if len(leads) >= max_leads:
                break

            logger.info("Scraping directory: %s", url)
            result = self.http.fetch(url)

            if not result.ok:
                logger.warning("Failed to fetch directory %s (status %d)", url, result.status_code)
                continue

            page_leads = self._extract_leads_from_html(result.text, url, keywords)
            leads.extend(page_leads)

        return leads[:max_leads]

    def _extract_leads_from_html(
        self, html: str, source_url: str, keywords: list[str]
    ) -> list[RawLead]:
        """Extract company information from a directory HTML page."""
        soup = BeautifulSoup(html, "lxml")
        leads: list[RawLead] = []

        # Strategy 1: Look for cards/list items with company info
        # Common patterns in directory pages
        selectors = [
            "div.member-card", "div.startup-card", "div.company-card",
            "div.portfolio-item", "li.member-item", "div.directory-entry",
            "article.post", "div.listing-item", "div.card",
        ]

        items = []
        for selector in selectors:
            items = soup.select(selector)
            if items:
                break

        if not items:
            # Fallback: look for structured data in links and headings
            items = self._find_company_blocks(soup)

        for item in items:
            lead = self._parse_directory_item(item, source_url)
            if lead:
                leads.append(lead)

        return leads

    def _find_company_blocks(self, soup: BeautifulSoup) -> list:
        """Heuristic to find company listing blocks in unstructured pages."""
        blocks = []

        # Look for divs/sections with multiple links (likely a listing)
        for container in soup.find_all(["div", "section", "ul"]):
            links = container.find_all("a", href=True)
            headings = container.find_all(["h2", "h3", "h4", "h5"])

            if len(links) >= 3 and len(headings) >= 2:
                # Likely a directory listing
                for heading in headings:
                    parent = heading.parent
                    if parent:
                        blocks.append(parent)

        return blocks[:50]  # Cap to avoid processing too many

    def _parse_directory_item(self, item, source_url: str) -> RawLead | None:
        """Parse a single directory listing item into a RawLead."""
        # Extract company name from heading or strong tag
        name_tag = item.find(["h2", "h3", "h4", "h5", "strong", "b"])
        if not name_tag:
            name_tag = item.find("a")

        if not name_tag or not name_tag.get_text(strip=True):
            return None

        company_name = name_tag.get_text(strip=True)

        # Skip obvious non-company entries
        if len(company_name) < 2 or len(company_name) > 100:
            return None

        # Extract domain from links
        domain = None
        website_url = None
        for link in item.find_all("a", href=True):
            href = link["href"]
            if href.startswith(("http://", "https://")) and not self._is_social_link(href):
                parsed = urlparse(href)
                if parsed.netloc and parsed.netloc != urlparse(source_url).netloc:
                    domain = parsed.netloc.lower().removeprefix("www.")
                    website_url = href
                    break

        # Extract description
        desc_tag = item.find("p") or item.find("span", class_=re.compile(r"desc|summary|bio"))
        description = desc_tag.get_text(strip=True) if desc_tag else None

        # Extract location
        location = None
        loc_tag = item.find(string=re.compile(r"(?i)(bangalore|mumbai|delhi|india|us|uk|singapore)"))
        if loc_tag:
            location = loc_tag.strip()[:100]

        # Extract emails
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", item.get_text())

        return self._make_lead(
            company_name=company_name,
            domain=domain,
            website_url=website_url,
            emails=emails,
            description=description,
            location=location,
            source_url=source_url,
            raw_data={"html_snippet": str(item)[:500]},
        )

    @staticmethod
    def _is_social_link(url: str) -> bool:
        """Check if a URL is a social media link."""
        social_domains = {
            "facebook.com", "twitter.com", "x.com", "linkedin.com",
            "instagram.com", "youtube.com", "github.com",
        }
        parsed = urlparse(url)
        return any(d in parsed.netloc for d in social_domains)
