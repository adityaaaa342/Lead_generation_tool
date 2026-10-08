"""LangGraph pipeline definition — wires all nodes into a state machine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from langgraph.graph import StateGraph, END

from leadpilot.config import Settings, get_settings
from leadpilot.collectors.base import BaseCollector
from leadpilot.collectors.directory_collector import DirectoryCollector
from leadpilot.collectors.osm_collector import OSMCollector
from leadpilot.collectors.github_collector import GitHubCollector
from leadpilot.collectors.reddit_collector import RedditCollector
from leadpilot.collectors.website_crawler import WebsiteCrawler
from leadpilot.llm.client import LLMClient
from leadpilot.models import (
    ICP,
    CollectionPlan,
    RawLead,
    CleanLead,
    EnrichedLead,
    ScoredLead,
)
from leadpilot.nodes.icp_builder import icp_builder
from leadpilot.nodes.source_router import source_router
from leadpilot.nodes.clean_dedupe import clean_dedupe
from leadpilot.nodes.enrich import enrich
from leadpilot.nodes.email_finder import email_finder
from leadpilot.nodes.score import score
from leadpilot.nodes.export import export
from leadpilot.utils.http import HTTPClient

logger = logging.getLogger(__name__)

# Collector registry
COLLECTOR_REGISTRY: dict[str, type[BaseCollector]] = {
    "directory_collector": DirectoryCollector,
    "osm_collector": OSMCollector,
    "github_collector": GitHubCollector,
    "reddit_collector": RedditCollector,
    "website_crawler": WebsiteCrawler,
}


def _merge_list(old: list, new: list) -> list:
    """Merge strategy for list fields in state — extend, don't replace."""
    return old + new


# State type annotations for LangGraph
from typing import TypedDict


class GraphState(TypedDict, total=False):
    """State flowing through the LangGraph pipeline."""

    brief: str
    limit: int
    icp: Optional[ICP]
    plan: Optional[CollectionPlan]
    raw_leads: Annotated[list[RawLead], _merge_list]
    clean_leads: list[CleanLead]
    enriched_leads: list[EnrichedLead]
    scored_leads: list[ScoredLead]
    errors: Annotated[list[str], _merge_list]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


def collect_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: Run all collectors specified in the plan.

    Dispatches to the appropriate collector classes based on the
    collection plan from source_router.
    """
    plan: CollectionPlan = state["plan"]
    icp: ICP = state["icp"]
    limit = state.get("limit", 50)

    settings = get_settings()
    http = HTTPClient(settings)

    all_leads: list[RawLead] = []
    errors: list[str] = []

    # Sort sources by priority
    sorted_sources = sorted(plan.sources, key=lambda s: s.priority)

    for source_config in sorted_sources:
        if len(all_leads) >= limit:
            break

        source_name = source_config.source_name
        collector_cls = COLLECTOR_REGISTRY.get(source_name)

        if collector_cls is None:
            logger.warning("Unknown collector: %s — skipping", source_name)
            errors.append(f"Unknown collector: {source_name}")
            continue

        logger.info(
            "Running collector: %s (priority=%d, max=%d)",
            source_name,
            source_config.priority,
            source_config.max_leads,
        )

        try:
            collector = collector_cls(settings=settings, http_client=http)
            leads = collector.collect(
                icp=icp,
                params=source_config.params,
                max_leads=min(source_config.max_leads, limit - len(all_leads)),
            )
            all_leads.extend(leads)
            logger.info("Collector %s returned %d leads", source_name, len(leads))
        except Exception as exc:
            logger.error("Collector %s failed: %s", source_name, exc)
            errors.append(f"Collector {source_name} failed: {exc}")

    logger.info("Total raw leads collected: %d", len(all_leads))
    return {"raw_leads": all_leads, "errors": errors}


def build_graph(settings: Settings | None = None) -> StateGraph:
    """Build the LangGraph pipeline.

    Returns a compiled StateGraph ready to invoke.
    """
    settings = settings or get_settings()
    llm = LLMClient(settings)
    http = HTTPClient(settings)

    # Create node wrappers that inject dependencies
    def icp_node(state):
        return icp_builder(state, llm=llm)

    def router_node(state):
        return source_router(state, llm=llm)

    def enrich_node(state):
        return enrich(state, llm=llm, http=http)

    def score_node(state):
        return score(state, llm=llm)

    # Build graph
    graph = StateGraph(GraphState)

    graph.add_node("icp_builder", icp_node)
    graph.add_node("source_router", router_node)
    graph.add_node("collect", collect_node)
    graph.add_node("clean_dedupe", clean_dedupe)
    graph.add_node("enrich", enrich_node)
    graph.add_node("email_finder", email_finder)
    graph.add_node("score", score_node)
    graph.add_node("export", export)

    # Define edges (linear pipeline)
    graph.set_entry_point("icp_builder")
    graph.add_edge("icp_builder", "source_router")
    graph.add_edge("source_router", "collect")
    graph.add_edge("collect", "clean_dedupe")
    graph.add_edge("clean_dedupe", "enrich")
    graph.add_edge("enrich", "email_finder")
    graph.add_edge("email_finder", "score")
    graph.add_edge("score", "export")
    graph.add_edge("export", END)

    return graph.compile()


def run_pipeline(
    brief: str,
    limit: int = 50,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the complete LeadPilot pipeline.

    Args:
        brief: User's business description.
        limit: Maximum leads to collect.
        settings: Optional settings override.

    Returns:
        Final pipeline state with scored_leads.
    """
    settings = settings or get_settings()
    graph = build_graph(settings)

    initial_state = {
        "brief": brief,
        "limit": limit,
        "started_at": datetime.now(timezone.utc),
        "raw_leads": [],
        "errors": [],
    }

    logger.info("Starting LeadPilot pipeline: brief=%s, limit=%d", brief[:80], limit)
    result = graph.invoke(initial_state)
    logger.info(
        "Pipeline complete: %d scored leads",
        len(result.get("scored_leads", [])),
    )

    return result
