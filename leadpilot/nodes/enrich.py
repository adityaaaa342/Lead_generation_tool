"""Node 5: Enrich — scrape websites and use LLM to extract structured data.

Step 1 improvement: Deterministic extraction runs FIRST (mailto/tel links,
regex emails/phones, schema.org JSON-LD parsing, meta tags).  The LLM is
called ONLY for fields that are still missing after deterministic extraction.
Every field is tagged with provenance so downstream nodes know where it came
from.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from leadpilot.llm.client import LLMClient
from leadpilot.llm.prompts import enrichment_messages
from leadpilot.models import CleanLead, EnrichedLead, FieldProvenance
from leadpilot.utils.http import HTTPClient

logger = logging.getLogger(__name__)

# ── Regex patterns ───────────────────────────────────────────────────────────

# RFC-5322-ish email — intentionally strict to avoid false positives
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Phone numbers: +country-code then digits/dashes/spaces/parens, 7-15 digits
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?"       # optional country code
    r"(?:\(?\d{2,5}\)?[\s\-.]?)?"     # optional area code
    r"\d[\d\s\-\.]{5,13}\d",          # number body (7-15 digits total)
)

# Common junk email prefixes we should skip
JUNK_EMAIL_PREFIXES = frozenset({
    "noreply", "no-reply", "donotreply", "mailer-daemon",
    "postmaster", "abuse", "webmaster", "root", "admin",
    "support", "help", "billing",
})

# Common generic email prefixes (lower priority than personal emails)
GENERIC_EMAIL_PREFIXES = frozenset({
    "info", "hello", "contact", "team", "sales", "enquiry",
    "enquiries", "office", "general", "mail",
})


# ── Deterministic extractors ────────────────────────────────────────────────


def _extract_mailto_emails(html: str) -> list[str]:
    """Extract email addresses from mailto: links in HTML."""
    soup = BeautifulSoup(html, "lxml")
    emails: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            # Strip mailto: and any query params (?subject=...)
            raw = href[7:].split("?")[0].strip()
            if raw and EMAIL_RE.fullmatch(raw):
                emails.append(raw.lower())
    return list(dict.fromkeys(emails))  # dedupe preserving order


def _extract_tel_phones(html: str) -> list[str]:
    """Extract phone numbers from tel: links in HTML."""
    soup = BeautifulSoup(html, "lxml")
    phones: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            raw = href[4:].strip()
            # Normalize: keep only digits, +, and hyphens
            cleaned = re.sub(r"[^\d+\-\s]", "", raw).strip()
            if cleaned and len(re.sub(r"\D", "", cleaned)) >= 7:
                phones.append(cleaned)
    return list(dict.fromkeys(phones))


def _extract_regex_emails(text: str) -> list[str]:
    """Extract emails from plain text using regex."""
    raw = EMAIL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for email in raw:
        email_lower = email.lower()
        prefix = email_lower.split("@")[0]
        # Skip obvious junk
        if prefix in JUNK_EMAIL_PREFIXES:
            continue
        # Skip image/file extensions misidentified as emails
        if email_lower.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js")):
            continue
        if email_lower not in seen:
            seen.add(email_lower)
            result.append(email_lower)
    return result


def _extract_regex_phones(text: str) -> list[str]:
    """Extract phone numbers from plain text using regex."""
    raw = PHONE_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for phone in raw:
        digits = re.sub(r"\D", "", phone)
        if 7 <= len(digits) <= 15 and digits not in seen:
            seen.add(digits)
            result.append(phone.strip())
    return result


def _parse_schema_org(schema_org: dict[str, Any]) -> dict[str, Any]:
    """Deterministically parse schema.org JSON-LD / microdata for business fields.

    Returns a flat dict of extracted fields (only non-None values).
    """
    extracted: dict[str, Any] = {}

    for syntax, items in schema_org.items():
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if not isinstance(item, dict):
                continue

            # Name / description
            if not extracted.get("description"):
                desc = item.get("description")
                if isinstance(desc, str) and len(desc.strip()) > 10:
                    extracted["description"] = desc.strip()

            # Email
            if not extracted.get("contact_email"):
                email = item.get("email")
                if isinstance(email, str) and EMAIL_RE.fullmatch(email.strip()):
                    extracted["contact_email"] = email.strip().lower()

            # Telephone
            if not extracted.get("phone"):
                phone = item.get("telephone")
                if isinstance(phone, str) and len(re.sub(r"\D", "", phone)) >= 7:
                    extracted["phone"] = phone.strip()

            # Founder / foundingDate
            if not extracted.get("founder_name"):
                founder = item.get("founder")
                if isinstance(founder, dict):
                    fname = founder.get("name")
                    if isinstance(fname, str) and len(fname.strip()) > 1:
                        extracted["founder_name"] = fname.strip()
                elif isinstance(founder, list):
                    for f in founder:
                        if isinstance(f, dict):
                            fname = f.get("name")
                            if isinstance(fname, str) and len(fname.strip()) > 1:
                                extracted["founder_name"] = fname.strip()
                                break

            if not extracted.get("founded_year"):
                fy = item.get("foundingDate")
                if fy:
                    try:
                        year = int(str(fy)[:4])
                        if 1800 <= year <= 2030:
                            extracted["founded_year"] = year
                    except (ValueError, TypeError):
                        pass

            # Industry
            if not extracted.get("industry"):
                ind = item.get("industry")
                if isinstance(ind, str) and len(ind.strip()) > 1:
                    extracted["industry"] = ind.strip()

            # Location
            if not extracted.get("location"):
                loc = item.get("address")
                if isinstance(loc, dict):
                    parts = [
                        loc.get("streetAddress"),
                        loc.get("addressLocality"),
                        loc.get("addressRegion"),
                        loc.get("addressCountry"),
                    ]
                    loc_str = ", ".join(p for p in parts if isinstance(p, str) and p.strip())
                    if loc_str:
                        extracted["location"] = loc_str
                elif isinstance(loc, str) and len(loc.strip()) > 2:
                    extracted["location"] = loc.strip()

            # Social links (sameAs)
            if not extracted.get("social_links"):
                same_as = item.get("sameAs", [])
                if isinstance(same_as, str):
                    same_as = [same_as]
                if isinstance(same_as, list) and same_as:
                    extracted["social_links"] = same_as

    return extracted


def _extract_meta_tags(html: str) -> dict[str, str]:
    """Extract useful business info from <meta> and Open Graph tags."""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}

    for tag in soup.find_all("meta"):
        name = (tag.get("name") or tag.get("property") or "").lower()
        content = (tag.get("content") or "").strip()
        if not content:
            continue

        if name in ("description", "og:description") and not meta.get("description"):
            if len(content) > 10:
                meta["description"] = content
        elif name in ("og:title",) and not meta.get("title"):
            meta["title"] = content
        elif name in ("og:site_name",) and not meta.get("site_name"):
            meta["site_name"] = content

    return meta


def _prioritize_emails(emails: list[str]) -> str | None:
    """Pick the best contact email: personal > generic > None."""
    personal: list[str] = []
    generic: list[str] = []

    for email in emails:
        prefix = email.split("@")[0]
        if prefix in GENERIC_EMAIL_PREFIXES:
            generic.append(email)
        else:
            personal.append(email)

    # Prefer personal emails, then generic
    return (personal + generic + [None])[0]


# ── Schema.org extraction (raw HTML → structured data) ──────────────────────


def _extract_schema_org(html: str) -> dict[str, Any]:
    """Extract schema.org structured data from HTML."""
    try:
        import extruct
        data = extruct.extract(html, syntaxes=["json-ld", "microdata", "opengraph"])

        # Flatten into a single dict
        result: dict[str, Any] = {}
        for syntax, items in data.items():
            if items:
                result[syntax] = items if isinstance(items, list) else [items]
        return result
    except Exception as exc:
        logger.debug("Schema.org extraction failed: %s", exc)
        return {}


# ── Page text extraction ────────────────────────────────────────────────────


def _extract_page_text(html: str) -> str:
    """Extract clean text from HTML using trafilatura with BS4 fallback."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if text:
            return text
    except Exception:
        pass

    # Fallback to BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


# ── Subpage discovery ───────────────────────────────────────────────────────


def _find_subpage_url(
    html: str, base_url: str, keywords: list[str]
) -> str | None:
    """Find a subpage URL (about, team, contact) from HTML links."""
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc

    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        text = link.get_text(strip=True).lower()

        if any(kw in href or kw in text for kw in keywords):
            full_url = urljoin(base_url, link["href"])
            if urlparse(full_url).netloc == base_domain:
                return full_url

    return None


# ── Social link categorization ──────────────────────────────────────────────


def _categorize_social(url: str, social_links: dict[str, str]) -> None:
    """Categorize a social media URL."""
    platforms = {
        "linkedin.com": "linkedin",
        "twitter.com": "twitter",
        "x.com": "twitter",
        "facebook.com": "facebook",
        "github.com": "github",
        "youtube.com": "youtube",
        "instagram.com": "instagram",
        "crunchbase.com": "crunchbase",
    }
    for domain, platform in platforms.items():
        if domain in url:
            social_links[platform] = url
            break


# ── Core enrichment logic ───────────────────────────────────────────────────


def enrich_lead(
    lead: CleanLead,
    http: HTTPClient,
    llm: LLMClient,
) -> EnrichedLead:
    """Enrich a single lead: deterministic extraction first, LLM only for gaps.

    Flow:
    1. Scrape homepage (+ about/team page if found)
    2. Deterministic extraction: mailto/tel links, regex, schema.org, meta tags
    3. LLM extraction: ONLY for fields still missing
    4. Tag every field with provenance
    """
    enrichment_sources: list[FieldProvenance] = []
    field_provenance: dict[str, str] = {}  # field_name → "scraped" | "llm_extract"

    # ── Step 1: Scrape ───────────────────────────────────────────────────
    page_html = ""
    page_text = ""
    schema_org: dict[str, Any] = {}

    if lead.website_url or lead.domain:
        url = lead.website_url or f"https://{lead.domain}"
        result = http.fetch(url)

        if result.ok:
            page_html = result.text
            page_text = _extract_page_text(result.text)
            schema_org = _extract_schema_org(result.text)
            enrichment_sources.append(FieldProvenance(
                source_url=url,
                collected_at=datetime.now(timezone.utc),
                method="scrape",
            ))

            # Try about/team pages for founder info
            about_url = _find_subpage_url(result.text, url, ["about", "team", "company"])
            if about_url:
                about_result = http.fetch(about_url)
                if about_result.ok:
                    about_text = _extract_page_text(about_result.text)
                    page_text += "\n\n=== ABOUT PAGE ===\n" + about_text
                    # Also extract from about page HTML
                    page_html += "\n" + about_result.text
                    enrichment_sources.append(FieldProvenance(
                        source_url=about_url,
                        collected_at=datetime.now(timezone.utc),
                        method="scrape",
                    ))

    # ── Step 2: Deterministic extraction ─────────────────────────────────

    det: dict[str, Any] = {}  # deterministically extracted fields

    # 2a. mailto: and tel: links from HTML
    if page_html:
        mailto_emails = _extract_mailto_emails(page_html)
        tel_phones = _extract_tel_phones(page_html)
    else:
        mailto_emails = []
        tel_phones = []

    # 2b. Regex emails and phones from page text
    regex_emails = _extract_regex_emails(page_text) if page_text else []
    regex_phones = _extract_regex_phones(page_text) if page_text else []

    # 2c. Schema.org JSON-LD / microdata
    schema_fields = _parse_schema_org(schema_org) if schema_org else {}

    # 2d. Meta tags (OG, description)
    meta_fields = _extract_meta_tags(page_html) if page_html else {}

    # ── Merge deterministic results (priority: mailto > schema > regex) ──

    # Contact email
    all_emails = mailto_emails + regex_emails
    if schema_fields.get("contact_email"):
        all_emails.insert(0, schema_fields["contact_email"])
    best_email = _prioritize_emails(list(dict.fromkeys(all_emails)))
    if best_email:
        det["contact_email"] = best_email
        field_provenance["contact_email"] = "scraped"

    # Phone
    all_phones = tel_phones + regex_phones
    if schema_fields.get("phone"):
        all_phones.insert(0, schema_fields["phone"])
    if lead.phone:
        all_phones.insert(0, lead.phone)
    if all_phones:
        det["phone"] = all_phones[0]
        field_provenance["phone"] = "scraped"

    # Description
    desc = schema_fields.get("description") or meta_fields.get("description")
    if desc:
        det["description"] = desc
        field_provenance["description"] = "scraped"

    # Founder name
    if schema_fields.get("founder_name"):
        det["founder_name"] = schema_fields["founder_name"]
        field_provenance["founder_name"] = "scraped"

    # Founded year
    if schema_fields.get("founded_year"):
        det["founded_year"] = schema_fields["founded_year"]
        field_provenance["founded_year"] = "scraped"

    # Industry
    if schema_fields.get("industry"):
        det["industry"] = schema_fields["industry"]
        field_provenance["industry"] = "scraped"

    # Location (prefer schema.org > lead.location)
    if schema_fields.get("location"):
        det["location"] = schema_fields["location"]
        field_provenance["location"] = "scraped"
    elif lead.location:
        det["location"] = lead.location
        field_provenance["location"] = "scraped"

    # Social links from schema.org sameAs
    social_links: dict[str, str] = {}
    if schema_fields.get("social_links"):
        for link in schema_fields["social_links"]:
            _categorize_social(link, social_links)
    # Also try direct schema_org parsing for sameAs (backward compat)
    if schema_org:
        for item_list in schema_org.values():
            if isinstance(item_list, list):
                for item in item_list:
                    if isinstance(item, dict):
                        same_as = item.get("sameAs", [])
                        if isinstance(same_as, list):
                            for link in same_as:
                                _categorize_social(link, social_links)
                        elif isinstance(same_as, str):
                            _categorize_social(same_as, social_links)

    # ── Step 3: LLM extraction — ONLY for missing fields ────────────────

    llm_data: dict[str, Any] = {}

    # Define which fields still need filling
    missing_fields = []
    for field in ("industry", "product_description", "size_guess",
                  "founded_year", "founder_name", "contact_email",
                  "technologies", "location"):
        if field not in det:
            missing_fields.append(field)

    if page_text and missing_fields:
        logger.info(
            "Deterministic extraction filled %d fields; asking LLM for %d missing: %s",
            len(det), len(missing_fields), missing_fields,
        )
        try:
            messages = enrichment_messages(
                company_name=lead.company_name,
                domain=lead.domain,
                page_text=page_text,
                schema_org=schema_org,
            )
            raw = llm.complete(messages)

            # Parse LLM response as JSON
            try:
                text = raw.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    text = "\n".join(lines)
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    llm_data = json.loads(text[start:end])
                    enrichment_sources.append(FieldProvenance(
                        source_url=lead.website_url or f"https://{lead.domain}",
                        collected_at=datetime.now(timezone.utc),
                        method="llm_extract",
                    ))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("LLM enrichment JSON parse failed for %s: %s", lead.company_name, exc)

        except Exception as exc:
            logger.warning("LLM enrichment failed for %s: %s", lead.company_name, exc)

        # Only use LLM values for fields that are STILL missing
        for field in missing_fields:
            llm_val = llm_data.get(field)
            if llm_val is not None and llm_val != "" and llm_val != []:
                det[field] = llm_val
                field_provenance[field] = "llm_extract"
    elif not page_text:
        logger.info("No page text for %s — skipping both deterministic and LLM extraction", lead.company_name)
    else:
        logger.info(
            "Deterministic extraction filled ALL fields for %s — skipping LLM call",
            lead.company_name,
        )

    # ── Step 4: Build EnrichedLead ───────────────────────────────────────

    return EnrichedLead(
        company_name=lead.company_name,
        domain=lead.domain,
        website_url=lead.website_url,
        emails=[],  # Will be populated by email_finder
        phone=det.get("phone") or lead.phone,
        description=det.get("description") or lead.description,
        location=det.get("location") or lead.location,
        sources=lead.sources,
        industry=det.get("industry"),
        product_description=det.get("product_description"),
        size_guess=det.get("size_guess"),
        founded_year=det.get("founded_year"),
        founder_name=det.get("founder_name"),
        contact_email=det.get("contact_email"),
        technologies=det.get("technologies", []),
        social_links=social_links,
        schema_org_data=schema_org,
        enrichment_sources=enrichment_sources,
        field_provenance=field_provenance,
    )


# ── LangGraph node wrapper ──────────────────────────────────────────────────


def enrich(
    state: dict[str, Any],
    llm: LLMClient | None = None,
    http: HTTPClient | None = None,
) -> dict[str, Any]:
    """LangGraph node: Enrich clean leads with website data and LLM extraction.

    Args:
        state: Pipeline state dict containing 'clean_leads'.
        llm: Optional LLMClient instance.
        http: Optional HTTPClient instance.

    Returns:
        Updated state dict with 'enriched_leads' populated.
    """
    clean_leads: list[CleanLead] = state["clean_leads"]
    logger.info("Enriching %d clean leads", len(clean_leads))

    if llm is None:
        llm = LLMClient()
    if http is None:
        http = HTTPClient()

    enriched_leads: list[EnrichedLead] = []
    errors: list[str] = state.get("errors", [])

    for i, lead in enumerate(clean_leads):
        logger.info("Enriching lead %d/%d: %s", i + 1, len(clean_leads), lead.company_name)
        try:
            enriched = enrich_lead(lead, http, llm)
            enriched_leads.append(enriched)
        except Exception as exc:
            logger.error("Failed to enrich %s: %s", lead.company_name, exc)
            errors.append(f"Enrich failed for {lead.company_name}: {exc}")
            # Still add with minimal enrichment
            enriched_leads.append(EnrichedLead(
                company_name=lead.company_name,
                domain=lead.domain,
                website_url=lead.website_url,
                phone=lead.phone,
                description=lead.description,
                location=lead.location,
                sources=lead.sources,
            ))

    return {"enriched_leads": enriched_leads, "errors": errors}
