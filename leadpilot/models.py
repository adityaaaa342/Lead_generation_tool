"""Pydantic models used throughout the LeadPilot pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── ICP (Ideal Customer Profile) ────────────────────────────────────────────


class ICP(BaseModel):
    """Structured Ideal Customer Profile generated from a business brief."""

    industry: list[str] = Field(description="Target industries (e.g. ['SaaS', 'FinTech'])")
    company_size_range: str = Field(
        description="Target company size (e.g. '1-50', '50-200', 'startup')"
    )
    locations: list[str] = Field(
        default_factory=list,
        description="Target geographies (e.g. ['India', 'US', 'Bangalore'])",
    )
    target_roles: list[str] = Field(
        description="Decision-maker roles to find (e.g. ['CTO', 'VP Engineering'])"
    )
    keywords: list[str] = Field(
        description="Search keywords relevant to this ICP"
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="Industries, company types, or keywords to exclude",
    )
    summary: str = Field(description="One-paragraph description of the ideal customer")


# ── Source Routing ───────────────────────────────────────────────────────────


class SourceConfig(BaseModel):
    """Configuration for a single lead source."""

    source_name: str = Field(description="Collector module name")
    priority: int = Field(default=1, ge=1, le=5, description="1=highest priority")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific parameters (URLs, queries, etc.)",
    )
    max_leads: int = Field(default=20, ge=1)


class CollectionPlan(BaseModel):
    """Output of source_router: which sources to query and how."""

    sources: list[SourceConfig]
    reasoning: str = Field(description="Why these sources were chosen")


# ── Leads at Various Stages ─────────────────────────────────────────────────


class FieldProvenance(BaseModel):
    """Tracks where a data field came from."""

    source_url: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    method: str = Field(default="scrape", description="scrape | api | llm_extract")


class RawLead(BaseModel):
    """A lead as it comes out of a collector — minimal structure."""

    company_name: str
    domain: Optional[str] = None
    website_url: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phone: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    source_name: str = Field(description="Which collector produced this")
    source_url: str = Field(description="URL where the lead was found")
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="All unstructured data from the source",
    )
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        # Strip protocol and trailing slashes
        for prefix in ("https://", "http://", "www."):
            if v.startswith(prefix):
                v = v[len(prefix):]
        return v.rstrip("/")


class CleanLead(BaseModel):
    """A lead after deduplication and normalization."""

    company_name: str
    domain: Optional[str] = None
    website_url: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phone: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    sources: list[FieldProvenance] = Field(
        default_factory=list,
        description="All sources this lead was found in",
    )
    merged_count: int = Field(default=1, description="Number of raw leads merged")


class EmailStatus(str, Enum):
    """Email verification result status."""

    VALID = "valid"
    RISKY = "risky"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class EmailResult(BaseModel):
    """Result of email verification."""

    email: str
    status: EmailStatus
    is_catchall: bool = False
    method: str = Field(description="How this email was found/verified")
    mx_records: list[str] = Field(default_factory=list)


class EnrichedLead(BaseModel):
    """A lead after enrichment — all available business intelligence filled in."""

    company_name: str
    domain: Optional[str] = None
    website_url: Optional[str] = None
    emails: list[EmailResult] = Field(default_factory=list)
    phone: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    sources: list[FieldProvenance] = Field(default_factory=list)

    # Enriched fields
    industry: Optional[str] = None
    product_description: Optional[str] = None
    size_guess: Optional[str] = None
    founded_year: Optional[int] = None
    founder_name: Optional[str] = None
    contact_email: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    social_links: dict[str, str] = Field(default_factory=dict)
    schema_org_data: dict[str, Any] = Field(default_factory=dict)

    # Provenance for enriched data
    enrichment_sources: list[FieldProvenance] = Field(default_factory=list)

    # Per-field provenance: maps field name → extraction method ("scraped" | "llm_extract")
    field_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps field names to how they were extracted: 'scraped' or 'llm_extract'",
    )


# ── Scoring ──────────────────────────────────────────────────────────────────


class ICPScores(BaseModel):
    """Individual scores per ICP criterion (each 0-20, total 0-100)."""

    industry_score: int = Field(ge=0, le=20, description="Industry match")
    size_score: int = Field(ge=0, le=20, description="Company size match")
    location_score: int = Field(ge=0, le=20, description="Location match")
    role_score: int = Field(ge=0, le=20, description="Decision-maker role fit")
    signal_score: int = Field(ge=0, le=20, description="Buying signals & keywords")

    @property
    def total(self) -> int:
        return (
            self.industry_score
            + self.size_score
            + self.location_score
            + self.role_score
            + self.signal_score
        )


class ScoredLead(BaseModel):
    """Final scored lead ready for export."""

    # Carry forward enriched fields
    company_name: str
    domain: Optional[str] = None
    website_url: Optional[str] = None
    emails: list[EmailResult] = Field(default_factory=list)
    phone: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    product_description: Optional[str] = None
    size_guess: Optional[str] = None
    founder_name: Optional[str] = None
    contact_email: Optional[str] = None

    # Scoring
    icp_scores: ICPScores
    total_score: int = Field(ge=0, le=100)
    reason: str = Field(description="One-line explanation of the score")

    # Provenance
    sources: list[FieldProvenance] = Field(default_factory=list)


# ── Pipeline State (for LangGraph) ──────────────────────────────────────────


class PipelineState(BaseModel):
    """State object that flows through the LangGraph pipeline."""

    # Input
    brief: str = Field(description="User's business description")
    limit: int = Field(default=50, description="Max leads to collect")

    # Outputs from each node (accumulated)
    icp: Optional[ICP] = None
    plan: Optional[CollectionPlan] = None
    raw_leads: list[RawLead] = Field(default_factory=list)
    clean_leads: list[CleanLead] = Field(default_factory=list)
    enriched_leads: list[EnrichedLead] = Field(default_factory=list)
    scored_leads: list[ScoredLead] = Field(default_factory=list)

    # Metadata
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
