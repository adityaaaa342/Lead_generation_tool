"""Shared test fixtures and mock data for LeadPilot tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from leadpilot.models import (
    ICP,
    RawLead,
    CleanLead,
    EnrichedLead,
    EmailResult,
    EmailStatus,
    ICPScores,
    ScoredLead,
    FieldProvenance,
)


@pytest.fixture
def sample_icp() -> ICP:
    """Sample ICP for testing."""
    return ICP(
        industry=["SaaS", "DevOps", "Cloud Infrastructure"],
        company_size_range="10-200",
        locations=["India", "US", "Bangalore"],
        target_roles=["CTO", "VP Engineering", "Head of DevOps"],
        keywords=["devops", "ci/cd", "kubernetes", "cloud", "automation"],
        exclusions=["consulting", "outsourcing"],
        summary="Mid-sized SaaS companies with engineering teams that need DevOps automation tools.",
    )


@pytest.fixture
def sample_raw_leads() -> list[RawLead]:
    """Sample raw leads with duplicates for testing dedup."""
    return [
        RawLead(
            company_name="Acme Corp",
            domain="acme.com",
            website_url="https://www.acme.com",
            emails=["info@acme.com"],
            description="Cloud infrastructure company",
            location="Bangalore, India",
            source_name="directory_collector",
            source_url="https://tie.org/members",
        ),
        RawLead(
            company_name="ACME Corporation",  # Duplicate: fuzzy name match
            domain="acme.com",  # Duplicate: same domain
            website_url="https://acme.com",
            emails=["contact@acme.com"],
            description="Cloud infra and DevOps",
            location="Bangalore",
            source_name="github_collector",
            source_url="https://github.com/acme",
        ),
        RawLead(
            company_name="Beta Labs",
            domain="betalabs.io",
            website_url="https://betalabs.io",
            emails=["hello@betalabs.io"],
            description="AI-powered testing platform",
            location="San Francisco, US",
            source_name="reddit_collector",
            source_url="https://reddit.com/r/startups/abc",
        ),
        RawLead(
            company_name="Gamma Technologies Pvt Ltd",
            domain="gammatech.in",
            website_url="https://gammatech.in",
            emails=["admin@gammatech.in"],
            description="Enterprise SaaS solutions",
            location="Mumbai, India",
            source_name="directory_collector",
            source_url="https://nasscom.in/members",
        ),
        RawLead(
            company_name="Gamma Tech",  # Duplicate: fuzzy name match
            domain="gammatech.in",  # Duplicate: same domain
            emails=["sales@gammatech.in"],
            source_name="osm_collector",
            source_url="https://openstreetmap.org/node/12345",
        ),
        RawLead(
            company_name="Delta AI",
            domain="delta-ai.com",
            website_url="https://delta-ai.com",
            emails=["team@delta-ai.com"],
            description="Machine learning ops platform",
            location="Hyderabad, India",
            source_name="github_collector",
            source_url="https://github.com/delta-ai",
        ),
        RawLead(
            company_name="Epsilon Cloud",
            domain="epsiloncloud.io",
            website_url="https://epsiloncloud.io",
            emails=[],
            description="Multi-cloud management",
            location="Delhi, India",
            source_name="website_crawler",
            source_url="https://epsiloncloud.io",
        ),
        RawLead(
            company_name="Zeta Software",
            domain="zetasoft.com",
            website_url="https://zetasoft.com",
            emails=["info@zetasoft.com", "careers@zetasoft.com"],
            description="HR tech for startups",
            location="Pune, India",
            source_name="directory_collector",
            source_url="https://tie.org/pune",
        ),
        RawLead(
            company_name="Eta Analytics",
            domain="eta-analytics.com",
            website_url="https://eta-analytics.com",
            description="Business intelligence platform",
            location="Chennai, India",
            source_name="reddit_collector",
            source_url="https://reddit.com/r/SaaS/xyz",
        ),
        RawLead(
            company_name="Theta Networks",
            domain="thetanet.io",
            website_url="https://thetanet.io",
            emails=["hello@thetanet.io"],
            description="Edge computing and CDN",
            location="Singapore",
            source_name="github_collector",
            source_url="https://github.com/thetanet",
        ),
    ]


@pytest.fixture
def sample_enriched_lead() -> EnrichedLead:
    """Sample enriched lead for scoring tests."""
    return EnrichedLead(
        company_name="Acme Corp",
        domain="acme.com",
        website_url="https://acme.com",
        emails=[],
        description="Cloud infrastructure and DevOps automation",
        location="Bangalore, India",
        sources=[
            FieldProvenance(
                source_url="https://tie.org/members",
                collected_at=datetime.now(timezone.utc),
            ),
        ],
        industry="SaaS / Cloud Infrastructure",
        product_description="DevOps automation platform for CI/CD pipelines",
        size_guess="50-100",
        founded_year=2019,
        founder_name="Raj Kumar",
        contact_email="raj@acme.com",
        technologies=["Kubernetes", "Docker", "Terraform"],
    )


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that returns predictable responses."""
    client = MagicMock()
    return client
