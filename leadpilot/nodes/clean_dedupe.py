"""Node 4: Clean & Deduplicate — normalize domains, merge duplicates."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from rapidfuzz import fuzz

from leadpilot.models import CleanLead, FieldProvenance, RawLead

logger = logging.getLogger(__name__)

# Threshold for fuzzy company name matching (0-100) — set high to avoid false merges
FUZZY_NAME_THRESHOLD = 92


def normalize_domain(domain: str | None) -> str | None:
    """Normalize a domain name for comparison."""
    if not domain:
        return None
    domain = domain.strip().lower()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    return domain.rstrip("/") or None


# Common company suffixes to strip during normalization (sorted by length descending)
COMPANY_SUFFIXES = (
    " private limited",
    " incorporated",
    " corporation",
    " pvt. ltd.",
    " pvt. ltd",
    " pvt ltd",
    " technologies",
    " technology",
    " solutions",
    " services",
    " software",
    " company",
    " limited",
    " inc.",
    " ltd.",
    " corp.",
    " pvt.",
    " group",
    " labs",
    " tech",
    " inc",
    " llc",
    " ltd",
    " corp",
    " co.",
    " lab",
)


def normalize_company_name(name: str) -> str:
    """Normalize a company name for comparison."""
    if not name:
        return ""
    name = name.strip().lower()
    # Remove special characters first
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Remove common suffixes iteratively
    changed = True
    while changed:
        changed = False
        for suffix in COMPANY_SUFFIXES:
            clean_suffix = re.sub(r"[^\w\s]", " ", suffix).strip()
            if name.endswith(" " + clean_suffix):
                name = name[: -len(clean_suffix) - 1].strip()
                changed = True
                break
            elif name == clean_suffix:
                break
    return name.strip()


def _normalize_location(loc: str | None) -> str | None:
    """Normalize a location string for comparison."""
    if not loc:
        return None
    loc = loc.strip().lower()
    # Remove coordinates like "12.34, 56.78"
    if re.match(r"^-?\d+\.\d+\s*,\s*-?\d+\.\d+$", loc):
        return None
    # Keep only the first meaningful part (city)
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    return parts[0] if parts else None


def _locations_conflict(loc_a: str | None, loc_b: str | None) -> bool:
    """Return True if two locations are clearly different cities.

    Returns False (no conflict) if either location is missing — we give
    the benefit of the doubt when data is incomplete.
    """
    norm_a = _normalize_location(loc_a)
    norm_b = _normalize_location(loc_b)
    if not norm_a or not norm_b:
        return False  # unknown — no conflict
    return norm_a != norm_b


def are_duplicates(lead_a: RawLead, lead_b: RawLead) -> bool:
    """Check if two raw leads represent the same company.

    Rules (evaluated in order):
    1. If both have domains → must match exactly (strongest signal).
    2. If email domains overlap → duplicate.
    3. Fuzzy company name match (≥92) BUT only if locations don't conflict.
    """
    domain_a = normalize_domain(lead_a.domain)
    domain_b = normalize_domain(lead_b.domain)

    # 1. Domain comparison — strongest signal, no location check needed
    if domain_a and domain_b:
        return domain_a == domain_b

    # 2. Email domain match (if at least one company domain is missing)
    emails_a = {e.split("@")[1].lower() for e in lead_a.emails if "@" in e}
    emails_b = {e.split("@")[1].lower() for e in lead_b.emails if "@" in e}

    if emails_a and emails_b and (emails_a & emails_b):
        return True

    # 3. Fuzzy company name match — require high threshold AND no location conflict
    name_a = normalize_company_name(lead_a.company_name)
    name_b = normalize_company_name(lead_b.company_name)

    if name_a and name_b:
        if name_a == name_b:
            # Exact normalized name match — still check location
            if _locations_conflict(lead_a.location, lead_b.location):
                logger.debug(
                    "Same name '%s' but different locations (%s vs %s) — not merging",
                    name_a, lead_a.location, lead_b.location,
                )
                return False
            return True

        score = fuzz.token_sort_ratio(name_a, name_b)
        if score >= FUZZY_NAME_THRESHOLD:
            # Fuzzy match — REQUIRE no location conflict
            if _locations_conflict(lead_a.location, lead_b.location):
                logger.debug(
                    "Fuzzy match '%s'≈'%s' (score=%d) but locations conflict (%s vs %s)",
                    name_a, name_b, score, lead_a.location, lead_b.location,
                )
                return False
            return True

    return False


def merge_leads(leads: list[RawLead]) -> CleanLead:
    """Merge a group of duplicate raw leads into a single clean lead."""
    # Use the lead with the most information as primary
    primary = max(leads, key=lambda l: _lead_richness(l))

    # Collect all unique data
    all_emails = list({e for l in leads for e in l.emails})
    all_sources = [
        FieldProvenance(
            source_url=l.source_url,
            collected_at=l.collected_at,
            method="scrape",
        )
        for l in leads
    ]

    # Prefer non-None values from any lead
    domain = primary.domain
    website_url = primary.website_url
    description = primary.description
    location = primary.location
    phone = primary.phone

    for lead in leads:
        if not domain and lead.domain:
            domain = lead.domain
        if not website_url and lead.website_url:
            website_url = lead.website_url
        if not description and lead.description:
            description = lead.description
        if not location and lead.location:
            location = lead.location
        if not phone and lead.phone:
            phone = lead.phone

    return CleanLead(
        company_name=primary.company_name,
        domain=normalize_domain(domain),
        website_url=website_url,
        emails=all_emails,
        phone=phone,
        description=description,
        location=location,
        sources=all_sources,
        merged_count=len(leads),
    )


def _lead_richness(lead: RawLead) -> int:
    """Score how much information a lead has (for merge priority)."""
    score = 0
    if lead.domain:
        score += 3
    if lead.website_url:
        score += 2
    if lead.emails:
        score += 2
    if lead.description:
        score += 1
    if lead.location:
        score += 1
    if lead.phone:
        score += 1
    return score


JUNK_NAME_KEYWORDS = (
    "please login",
    "login/register",
    "sign in",
    "sign up",
    "contact us",
    "about us",
    "privacy policy",
    "terms of",
    "cookie policy",
    "do you really want",
    "last updated",
    "filter",
    "navigation",
    "error",
    "untitled",
    "click here",
    "read more",
    "copyright",
    "all rights reserved",
    "join bhaskar",
)


def is_valid_lead_name(name: str | None) -> bool:
    """Filter out scraped web UI artifacts and navigation text."""
    if not name or len(name.strip()) < 2:
        return False
    lower = name.lower().strip()
    if any(junk in lower for junk in JUNK_NAME_KEYWORDS):
        return False
    if lower.startswith("<") or "</" in lower:
        return False
    return True


def clean_dedupe(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: Normalize and deduplicate raw leads.

    Args:
        state: Pipeline state dict containing 'raw_leads'.

    Returns:
        Updated state dict with 'clean_leads' populated.
    """
    all_raw: list[RawLead] = state["raw_leads"]
    raw_leads = [l for l in all_raw if is_valid_lead_name(l.company_name)]
    logger.info("Filtered %d raw leads → %d valid leads", len(all_raw), len(raw_leads))

    if not raw_leads:
        return {"clean_leads": []}

    # Build groups of duplicates using union-find style approach
    n = len(raw_leads)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # O(n^2) pairwise comparison — fine for typical lead counts (<1000)
    for i in range(n):
        for j in range(i + 1, n):
            if are_duplicates(raw_leads[i], raw_leads[j]):
                union(i, j)

    # Group leads by their root parent
    groups: dict[int, list[RawLead]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(raw_leads[i])

    # Merge each group
    clean_leads = [merge_leads(group) for group in groups.values()]

    logger.info(
        "Deduplicated %d raw leads → %d clean leads (removed %d dupes)",
        len(raw_leads),
        len(clean_leads),
        len(raw_leads) - len(clean_leads),
    )

    return {"clean_leads": clean_leads}
