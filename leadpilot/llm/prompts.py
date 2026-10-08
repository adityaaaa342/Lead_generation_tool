"""Prompt templates for LLM-powered pipeline nodes."""

from __future__ import annotations

import json
from typing import Any

from leadpilot.models import ICP, ICPScores


# ── System Prompts ───────────────────────────────────────────────────────────

SYSTEM_JSON = (
    "You are a data extraction assistant. "
    "Always respond with ONLY valid JSON matching the requested schema. "
    "No markdown fences, no explanation — just the JSON object."
)

SYSTEM_SCORING = (
    "You are a B2B lead qualification expert. "
    "Score each lead against the Ideal Customer Profile. "
    "Be precise and justified in your scoring."
)


# ── ICP Builder ──────────────────────────────────────────────────────────────

def icp_builder_messages(brief: str) -> list[dict[str, str]]:
    """Build messages for ICP generation from a user's business brief."""
    schema = json.dumps(ICP.model_json_schema(), indent=2)
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {
            "role": "user",
            "content": (
                f"A business describes itself as follows:\n\n"
                f'"{brief}"\n\n'
                f"Based on this description, create a structured Ideal Customer Profile (ICP). "
                f"Think about:\n"
                f"1. What industries would buy this product/service?\n"
                f"2. What size companies are the best fit?\n"
                f"3. Where are they located?\n"
                f"4. Who are the decision-makers to target?\n"
                f"5. What keywords would help find these companies?\n"
                f"6. What should be excluded?\n\n"
                f"Respond with JSON matching this schema:\n"
                f"```json\n{schema}\n```"
            ),
        },
    ]


# ── Source Router ────────────────────────────────────────────────────────────

def source_router_messages(icp: ICP, available_sources: list[str]) -> list[dict[str, str]]:
    """Build messages for source selection based on ICP."""
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {
            "role": "user",
            "content": (
                f"Given this Ideal Customer Profile:\n"
                f"{icp.model_dump_json(indent=2)}\n\n"
                f"And these available lead sources:\n"
                f"{json.dumps(available_sources, indent=2)}\n\n"
                f"Select which sources are most likely to find matching leads. "
                f"For each selected source, specify:\n"
                f"- source_name: one of the available sources\n"
                f"- priority: 1 (highest) to 5 (lowest)\n"
                f"- params: any relevant parameters (search queries, locations, etc.)\n"
                f"- max_leads: how many leads to try to collect from this source\n\n"
                f"Also explain your reasoning.\n\n"
                f'Respond with JSON: {{"sources": [...], "reasoning": "..."}}'
            ),
        },
    ]


# ── Enrichment ───────────────────────────────────────────────────────────────

def enrichment_messages(
    company_name: str,
    domain: str | None,
    page_text: str,
    schema_org: dict[str, Any],
) -> list[dict[str, str]]:
    """Build messages for extracting structured company data from web content."""
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {
            "role": "user",
            "content": (
                f"Extract business information about '{company_name}' "
                f"(domain: {domain or 'unknown'}) from the following web page content "
                f"and structured data.\n\n"
                f"=== PAGE TEXT (trimmed) ===\n{page_text[:3000]}\n\n"
                f"=== SCHEMA.ORG DATA ===\n{json.dumps(schema_org, indent=2, default=str)[:1500]}\n\n"
                f"Extract and return JSON with these fields:\n"
                f'{{"industry": "...", "product_description": "one line", '
                f'"size_guess": "e.g. 1-10 or 50-200", '
                f'"founded_year": 2020, '
                f'"founder_name": "...", '
                f'"contact_email": "...", '
                f'"technologies": ["..."], '
                f'"location": "city, country"}}\n\n'
                f"Use null for any field you cannot determine. Do not guess emails."
            ),
        },
    ]


# ── Scoring ──────────────────────────────────────────────────────────────────

def scoring_messages(icp: ICP, lead_summary: dict[str, Any]) -> list[dict[str, str]]:
    """Build messages for scoring a lead against the ICP."""
    schema = json.dumps(ICPScores.model_json_schema(), indent=2)
    return [
        {"role": "system", "content": SYSTEM_SCORING},
        {
            "role": "user",
            "content": (
                f"Score this lead against the Ideal Customer Profile.\n\n"
                f"=== ICP ===\n{icp.model_dump_json(indent=2)}\n\n"
                f"=== LEAD ===\n{json.dumps(lead_summary, indent=2, default=str)}\n\n"
                f"Score each criterion from 0 to 20:\n"
                f"- industry_score: How well does the lead's industry match?\n"
                f"- size_score: Does the company size fit?\n"
                f"- location_score: Is the location a match?\n"
                f"- role_score: Are the right decision-makers accessible?\n"
                f"- signal_score: Are there buying signals or keyword matches?\n\n"
                f"Respond with JSON matching this schema:\n"
                f"```json\n{schema}\n```"
            ),
        },
    ]


def scoring_reason_messages(
    icp: ICP, lead_summary: dict[str, Any], scores: ICPScores
) -> list[dict[str, str]]:
    """Build messages for generating a one-line scoring reason."""
    return [
        {"role": "system", "content": SYSTEM_SCORING},
        {
            "role": "user",
            "content": (
                f"You scored this lead {scores.total}/100 against the ICP.\n\n"
                f"Scores: industry={scores.industry_score}, size={scores.size_score}, "
                f"location={scores.location_score}, role={scores.role_score}, "
                f"signals={scores.signal_score}\n\n"
                f"ICP summary: {icp.summary}\n\n"
                f"Lead: {lead_summary.get('company_name', 'Unknown')} — "
                f"{lead_summary.get('industry', 'unknown industry')}, "
                f"{lead_summary.get('size_guess', 'unknown size')}, "
                f"{lead_summary.get('location', 'unknown location')}\n\n"
                f"Write ONE sentence explaining why this lead scored {scores.total}/100. "
                f"Be specific about what matched and what didn't.\n\n"
                f'Respond with JSON: {{"reason": "your one sentence here"}}'
            ),
        },
    ]
