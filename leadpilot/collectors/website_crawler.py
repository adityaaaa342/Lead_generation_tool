"""Company website crawler — follow links on a known company URL."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from leadpilot.collectors.base import BaseCollector
from leadpilot.models import ICP, RawLead

logger = logging.getLogger(__name__)


class WebsiteCrawler(BaseCollector):
    """Crawl company websites to extract business information."""

    SOURCE_NAME = "website_crawler"

    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Crawl given company URLs to create/enrich leads.

        Params must include:
            - urls: list of company website URLs to crawl
        """
        params = params or {}
        urls = params.get("urls", [])
        leads: list[RawLead] = []

        for url in urls[:max_leads]:
            lead = self._crawl_site(url)
            if lead:
                leads.append(lead)

        return leads

    def _crawl_site(self, url: str) -> RawLead | None:
        """Crawl a single website and extract company info."""
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        result = self.http.fetch(url)
        if not result.ok:
            logger.warning("Failed to crawl %s (status %d)", url, result.status_code)
            return None

        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower().removeprefix("www.")

        soup = BeautifulSoup(result.text, "lxml")

        # Extract basic info from homepage
        title = soup.title.get_text(strip=True) if soup.title else domain
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")

        # Extract emails
        emails = list(set(re.findall(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            result.text
        )))

        # Extract phone numbers (simple pattern)
        phones = re.findall(r'[\+]?[\d\s\-\(\)]{10,15}', result.text)
        phone = phones[0].strip() if phones else None

        # Try to find about/contact pages for more info
        about_text = self._fetch_subpage(url, soup, ["about", "team", "company"])
        contact_text = self._fetch_subpage(url, soup, ["contact", "contact-us"])

        # Merge emails from subpages
        if about_text:
            emails.extend(re.findall(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                about_text,
            ))
        if contact_text:
            emails.extend(re.findall(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                contact_text,
            ))

        emails = list(set(emails))[:5]  # Dedupe and cap

        # Company name: prefer og:title or site name
        company_name = title
        og_site = soup.find("meta", property="og:site_name")
        if og_site:
            company_name = og_site.get("content", title)

        return self._make_lead(
            company_name=company_name,
            domain=domain,
            website_url=url,
            emails=emails,
            phone=phone,
            description=meta_desc or title,
            source_url=url,
            raw_data={
                "title": title,
                "meta_description": meta_desc,
                "about_text": (about_text or "")[:500],
                "contact_text": (contact_text or "")[:500],
            },
        )

    def _fetch_subpage(
        self, base_url: str, soup: BeautifulSoup, keywords: list[str]
    ) -> str | None:
        """Find and fetch a subpage (about, contact, team) by link text/href."""
        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            text = link.get_text(strip=True).lower()

            if any(kw in href or kw in text for kw in keywords):
                full_url = urljoin(base_url, link["href"])
                # Only follow same-domain links
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    result = self.http.fetch(full_url)
                    if result.ok:
                        sub_soup = BeautifulSoup(result.text, "lxml")
                        # Extract main text content
                        for tag in sub_soup(["script", "style", "nav", "footer"]):
                            tag.decompose()
                        return sub_soup.get_text(separator=" ", strip=True)[:3000]

        return None
