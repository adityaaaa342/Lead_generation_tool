"""Node 7: Score — rule-based scoring against the ICP.

Step 5 improvement: Replaced LLM-based scoring with deterministic, verifiable
rules. Each criterion is scored by comparing observed lead data against the ICP.

Scoring rubric (each 0-20, total 0-100):

  industry_score  — Does the lead's industry match the ICP target industries?
  size_score      — Does the company size match the ICP size range?
  location_score  — Is the lead in a target location?
  role_score      — Does the lead have a discoverable decision-maker contact?
  signal_score    — Do the lead keywords/description match the ICP keywords?

The LLM is no longer called during scoring.  A human-readable reason string is
assembled from code — it only cites facts that are actually in the lead data.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel

from leadpilot.models import (
    EnrichedLead,
    ICP,
    ICPScores,
    ScoredLead,
)

logger = logging.getLogger(__name__)


# ── Backward-compatibility stubs ─────────────────────────────────────────────

class ReasonResponse(BaseModel):
    """Kept for import compatibility. No longer used by the scoring pipeline."""
    reason: str


def _lead_to_summary(lead: EnrichedLead) -> dict[str, Any]:
    """Convert an enriched lead to a summary dict (kept for test compatibility)."""
    return {
        "company_name": lead.company_name,
        "domain": lead.domain,
        "industry": lead.industry,
        "product_description": lead.product_description,
        "size_guess": lead.size_guess,
        "location": lead.location,
        "founder_name": lead.founder_name,
        "technologies": lead.technologies,
        "description": lead.description,
    }



def _normalize(text: str | None) -> str:
    """Lowercase and collapse whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _any_match(haystack: str, needles: list[str]) -> bool:
    """Return True if any needle appears in haystack (case-insensitive)."""
    for needle in needles:
        if needle.lower() in haystack:
            return True
    return False


def _parse_size_range(size_str: str) -> tuple[int, int]:
    """Parse '1-50', '50-200', 'startup' etc into (min, max) employee count."""
    size_str = size_str.strip().lower()
    # "startup" / "small" shortcuts
    PRESETS = {
        "startup": (1, 20),
        "small": (1, 50),
        "mid": (50, 250),
        "medium": (50, 250),
        "large": (250, 5000),
        "enterprise": (1000, 999_999),
    }
    for key, val in PRESETS.items():
        if key in size_str:
            return val
    # Try "N-M" or "N to M"
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)", size_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Single number
    m = re.search(r"(\d+)", size_str)
    if m:
        n = int(m.group(1))
        return max(0, n - 5), n + 5
    return 0, 999_999  # unknown → accept anything


def _parse_lead_size(size_guess: str | None) -> int | None:
    """Extract a single employee-count estimate from a free-text size_guess."""
    if not size_guess:
        return None
    # Look for things like "10-20 employees", "~50 staff", "small team of 5"
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)", size_guess)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    m = re.search(r"(\d+)", size_guess)
    if m:
        return int(m.group(1))
    return None


# ── Per-criterion scorers ─────────────────────────────────────────────────────

def _score_industry(lead: EnrichedLead, icp: ICP) -> tuple[int, str]:
    """0-20: Does the lead's industry match the ICP?"""
    if not icp.industry:
        return 10, "no industry filter in ICP"

    haystack = " ".join([
        _normalize(lead.industry),
        _normalize(lead.description),
        _normalize(lead.product_description),
    ])

    if not haystack.strip():
        return 5, "no industry data available for lead"

    matches = [ind for ind in icp.industry if ind.lower() in haystack]
    if matches:
        return 20, f"industry matches: {', '.join(matches)}"

    # Check exclusions
    if lead.industry:
        excluded = [ex for ex in icp.exclusions if ex.lower() in haystack]
        if excluded:
            return 0, f"excluded industry: {', '.join(excluded)}"

    return 5, "industry not confirmed in ICP target list"


def _score_size(lead: EnrichedLead, icp: ICP) -> tuple[int, str]:
    """0-20: Does the company size match the ICP size range?"""
    icp_min, icp_max = _parse_size_range(icp.company_size_range)
    lead_size = _parse_lead_size(lead.size_guess)

    if lead_size is None:
        return 8, "company size unknown"

    if icp_min <= lead_size <= icp_max:
        return 20, f"size {lead_size} is within ICP range {icp_min}–{icp_max}"

    # Partial credit if close (within 2x range)
    if lead_size < icp_min and lead_size >= icp_min // 2:
        return 10, f"size {lead_size} is slightly below ICP range {icp_min}–{icp_max}"
    if lead_size > icp_max and lead_size <= icp_max * 2:
        return 10, f"size {lead_size} is slightly above ICP range {icp_min}–{icp_max}"

    return 0, f"size {lead_size} is outside ICP range {icp_min}–{icp_max}"


def _score_location(lead: EnrichedLead, icp: ICP) -> tuple[int, str]:
    """0-20: Is the lead in a target geography?"""
    if not icp.locations:
        return 10, "no location filter in ICP"
    if not lead.location:
        return 5, "lead location unknown"

    lead_loc = _normalize(lead.location)
    matches = [loc for loc in icp.locations if loc.lower() in lead_loc]
    if matches:
        return 20, f"location '{lead.location}' matches ICP: {', '.join(matches)}"
    return 0, f"location '{lead.location}' not in ICP target locations"


def _score_role(lead: EnrichedLead, icp: ICP) -> tuple[int, str]:
    """0-20: Can we reach a decision-maker?

    Scored purely on verifiable contact data — not on hallucinated names.
    """
    prov = getattr(lead, "field_provenance", {}) or {}
    founder_source = prov.get("founder_name", "unknown")
    contact_source = prov.get("contact_email", "unknown")

    score = 0
    reasons = []

    # Verified contact email = strong signal
    if lead.contact_email and contact_source == "scraped":
        score += 10
        reasons.append(f"scraped contact email: {lead.contact_email}")
    elif lead.contact_email:
        score += 5
        reasons.append(f"contact email (unverified): {lead.contact_email}")

    # Verified founder name = decision-maker present
    if lead.founder_name and founder_source == "scraped":
        score += 10
        reasons.append(f"scraped founder: {lead.founder_name}")
    elif lead.founder_name:
        score += 3
        reasons.append("founder name (LLM-extracted, lower confidence)")

    score = min(score, 20)
    reason = "; ".join(reasons) if reasons else "no contact information found"
    return score, reason


def _score_signals(lead: EnrichedLead, icp: ICP) -> tuple[int, str]:
    """0-20: Do the lead's keywords match the ICP buying signals?"""
    if not icp.keywords:
        return 10, "no keyword signals in ICP"

    haystack = " ".join([
        _normalize(lead.description),
        _normalize(lead.product_description),
        _normalize(lead.industry),
        " ".join(_normalize(t) for t in (lead.technologies or [])),
    ])

    if not haystack.strip():
        return 5, "no descriptive data to match signals"

    matches = [kw for kw in icp.keywords if kw.lower() in haystack]
    if not matches:
        return 0, "no ICP keywords found in lead data"

    # Scale: 1 keyword = 5, 2 = 10, 3 = 15, 4+ = 20
    score = min(len(matches) * 5, 20)
    return score, f"keywords matched: {', '.join(matches[:5])}"


# ── Main scoring function ─────────────────────────────────────────────────────

def score_lead(
    lead: EnrichedLead,
    icp: ICP,
    llm=None,  # kept for signature compatibility; not used
) -> ScoredLead:
    """Score a single lead against the ICP using deterministic rules.

    Args:
        lead: Enriched lead to score.
        icp:  ICP to score against.
        llm:  Ignored. Kept for API compatibility.

    Returns:
        ScoredLead with per-criterion scores and a factual reason string.
    """
    ind_score, ind_reason = _score_industry(lead, icp)
    size_score, size_reason = _score_size(lead, icp)
    loc_score, loc_reason = _score_location(lead, icp)
    role_score, role_reason = _score_role(lead, icp)
    sig_score, sig_reason = _score_signals(lead, icp)

    icp_scores = ICPScores(
        industry_score=ind_score,
        size_score=size_score,
        location_score=loc_score,
        role_score=role_score,
        signal_score=sig_score,
    )
    total_score = icp_scores.total

    # Build a concise, factual reason string
    parts = [
        f"industry={ind_score}/20 ({ind_reason})",
        f"size={size_score}/20 ({size_reason})",
        f"location={loc_score}/20 ({loc_reason})",
        f"contact={role_score}/20 ({role_reason})",
        f"signals={sig_score}/20 ({sig_reason})",
    ]
    reason = f"Score {total_score}/100 — " + " | ".join(parts)

    logger.debug("Scored %s: %d/100", lead.company_name, total_score)

    return ScoredLead(
        company_name=lead.company_name,
        domain=lead.domain,
        website_url=lead.website_url,
        emails=lead.emails,
        phone=lead.phone,
        description=lead.description,
        location=lead.location,
        industry=lead.industry,
        product_description=lead.product_description,
        size_guess=lead.size_guess,
        founder_name=lead.founder_name,
        contact_email=lead.contact_email,
        icp_scores=icp_scores,
        total_score=total_score,
        reason=reason,
        sources=lead.sources,
    )


def score(
    state: dict[str, Any],
    llm=None,
) -> dict[str, Any]:
    """LangGraph node: Score all enriched leads against the ICP.

    Args:
        state: Pipeline state dict containing 'enriched_leads' and 'icp'.
        llm:   Ignored (scoring is now rule-based). Kept for API compatibility.

    Returns:
        Updated state dict with 'scored_leads' populated, sorted by score.
    """
    enriched_leads: list[EnrichedLead] = state["enriched_leads"]
    icp: ICP = state["icp"]

    logger.info("Scoring %d leads against ICP (rule-based)", len(enriched_leads))

    scored_leads: list[ScoredLead] = []
    errors: list[str] = state.get("errors", [])

    for i, lead in enumerate(enriched_leads):
        logger.info(
            "Scoring lead %d/%d: %s", i + 1, len(enriched_leads), lead.company_name
        )
        try:
            scored = score_lead(lead, icp)
            scored_leads.append(scored)
        except Exception as exc:
            logger.error("Failed to score %s: %s", lead.company_name, exc)
            errors.append(f"Score failed for {lead.company_name}: {exc}")
            scored_leads.append(ScoredLead(
                company_name=lead.company_name,
                domain=lead.domain,
                website_url=lead.website_url,
                emails=lead.emails,
                description=lead.description,
                location=lead.location,
                industry=lead.industry,
                size_guess=lead.size_guess,
                founder_name=lead.founder_name,
                icp_scores=ICPScores(
                    industry_score=0, size_score=0, location_score=0,
                    role_score=0, signal_score=0,
                ),
                total_score=0,
                reason=f"Scoring failed: {exc}",
                sources=lead.sources,
            ))

    # Sort by score descending
    scored_leads.sort(key=lambda l: l.total_score, reverse=True)

    logger.info(
        "Scoring complete. Top score: %d, Bottom score: %d",
        scored_leads[0].total_score if scored_leads else 0,
        scored_leads[-1].total_score if scored_leads else 0,
    )

    return {"scored_leads": scored_leads, "errors": errors}
