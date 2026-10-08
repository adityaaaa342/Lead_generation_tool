"""Node 2: Source Router — decide which collectors to use based on the ICP.

Step 4 improvement: Replaced LLM-based routing with deterministic rule-based
routing.  The ICP keywords and industries are matched against known collector
capabilities using simple keyword matching.  This is faster, cheaper, and
more predictable than asking the LLM to pick collectors.
"""

from __future__ import annotations

import logging
from typing import Any

from leadpilot.models import CollectionPlan, ICP, SourceConfig

logger = logging.getLogger(__name__)

# All available collector modules
AVAILABLE_SOURCES = [
    "directory_collector",   # TiE-style incubator/directory member pages
    "osm_collector",         # OpenStreetMap Overpass API for local businesses
    "github_collector",      # GitHub public API (orgs, users, repos)
    "reddit_collector",      # Reddit public API (startup communities)
    "website_crawler",       # General website crawler for company sites
]

# ── Rule-based routing tables ───────────────────────────────────────────────

# Keywords that indicate a LOCAL / physical business → OSM is the best source
OSM_KEYWORDS = frozenset({
    "restaurant", "cafe", "coffee", "salon", "beauty", "spa", "fitness",
    "gym", "hotel", "motel", "hostel", "clinic", "dental", "dentist",
    "hospital", "healthcare", "real estate", "retail", "shop", "store",
    "bakery", "bar", "pub", "pharmacy", "grocery", "supermarket",
    "laundry", "dry clean", "veterinary", "pet", "florist", "car wash",
    "auto repair", "mechanic", "gas station", "coworking", "yoga",
    "pilates", "martial arts", "dance", "education", "school",
    "university", "tutoring", "daycare", "nursery", "kindergarten",
    "church", "temple", "mosque", "synagogue", "worship",
    "manufacturing", "logistics", "warehouse", "factory",
})

# Keywords that indicate a TECH / startup business → GitHub + Reddit
TECH_KEYWORDS = frozenset({
    "saas", "software", "tech", "startup", "api", "cloud", "devops",
    "ai", "machine learning", "ml", "data science", "analytics",
    "fintech", "edtech", "healthtech", "biotech", "blockchain",
    "crypto", "web3", "mobile app", "platform", "developer",
    "open source", "oss", "engineering",
})

# Keywords for directory/incubator sources
DIRECTORY_KEYWORDS = frozenset({
    "startup", "incubator", "accelerator", "venture", "vc",
    "funded", "series a", "seed", "angel", "tie", "nasscom",
    "portfolio",
})


def _match_keywords(text_parts: list[str], keyword_set: frozenset[str]) -> int:
    """Count how many keywords from the set appear in the text parts.

    Returns a match count — higher means stronger signal.
    """
    joined = " ".join(text_parts).lower()
    return sum(1 for kw in keyword_set if kw in joined)


def source_router(state: dict[str, Any], llm=None) -> dict[str, Any]:
    """LangGraph node: Route the ICP to appropriate lead sources.

    Uses deterministic keyword matching instead of LLM.
    The `llm` parameter is kept for API compatibility but ignored.

    Args:
        state: Pipeline state dict containing 'icp'.

    Returns:
        Updated state dict with 'plan' populated.
    """
    icp: ICP = state["icp"]
    limit = state.get("limit", 50)

    logger.info("Routing ICP to sources (limit=%d) — rule-based", limit)

    # Combine all ICP text for keyword matching
    text_parts = (
        icp.industry
        + icp.keywords
        + icp.locations
        + [icp.summary]
    )

    osm_score = _match_keywords(text_parts, OSM_KEYWORDS)
    tech_score = _match_keywords(text_parts, TECH_KEYWORDS)
    dir_score = _match_keywords(text_parts, DIRECTORY_KEYWORDS)

    sources: list[SourceConfig] = []
    reasoning_parts: list[str] = []

    # ── Always include website_crawler as a fallback ─────────────────────
    # (it can crawl any URL the other collectors find)

    # ── OSM: local/physical businesses ──────────────────────────────────
    if osm_score > 0:
        sources.append(SourceConfig(
            source_name="osm_collector",
            priority=1,
            params={},
            max_leads=min(limit, 30),
        ))
        reasoning_parts.append(
            f"OSM selected (matched {osm_score} local-business keywords)"
        )

    # ── GitHub: tech/startup companies ──────────────────────────────────
    if tech_score > 0:
        sources.append(SourceConfig(
            source_name="github_collector",
            priority=2 if osm_score == 0 else 3,
            params={},
            max_leads=min(limit, 20),
        ))
        reasoning_parts.append(
            f"GitHub selected (matched {tech_score} tech keywords)"
        )

    # ── Reddit: startup communities ─────────────────────────────────────
    if tech_score > 0 or dir_score > 0:
        sources.append(SourceConfig(
            source_name="reddit_collector",
            priority=3,
            params={},
            max_leads=min(limit, 15),
        ))
        reasoning_parts.append("Reddit selected (tech/startup community)")

    # ── Directory: incubator/accelerator leads ──────────────────────────
    if dir_score > 0:
        sources.append(SourceConfig(
            source_name="directory_collector",
            priority=2,
            params={},
            max_leads=min(limit, 20),
        ))
        reasoning_parts.append(
            f"Directory selected (matched {dir_score} incubator keywords)"
        )

    # ── Fallback: if nothing matched, use OSM + website_crawler ─────────
    if not sources:
        sources.append(SourceConfig(
            source_name="osm_collector",
            priority=1,
            params={},
            max_leads=min(limit, 25),
        ))
        sources.append(SourceConfig(
            source_name="website_crawler",
            priority=2,
            params={},
            max_leads=min(limit, 15),
        ))
        reasoning_parts.append(
            "No strong keyword matches — defaulting to OSM + website crawler"
        )

    # Cap total max_leads
    total_planned = sum(s.max_leads for s in sources)
    if total_planned > limit * 2:
        scale = (limit * 2) / total_planned
        for source in sources:
            source.max_leads = max(5, int(source.max_leads * scale))

    reasoning = "; ".join(reasoning_parts)
    logger.info(
        "Source plan: %s (reasoning: %s)",
        [s.source_name for s in sources],
        reasoning,
    )

    plan = CollectionPlan(sources=sources, reasoning=reasoning)
    return {"plan": plan}
