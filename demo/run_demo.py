"""Demo script — run the pipeline offline with mocked collectors and LLM."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from leadpilot.models import (
    ICP,
    CollectionPlan,
    ICPScores,
    RawLead,
    ScoredLead,
    SourceConfig,
    CleanLead,
    EnrichedLead,
    EmailResult,
    EmailStatus,
    FieldProvenance,
)
from leadpilot.nodes.clean_dedupe import clean_dedupe
from leadpilot.nodes.export import export_to_excel, leads_to_dataframe


def load_mock_leads() -> list[RawLead]:
    """Load demo leads from mock_leads.json."""
    mock_file = Path(__file__).parent / "mock_leads.json"
    with open(mock_file) as f:
        data = json.load(f)
    return [RawLead(**lead) for lead in data]


def mock_icp() -> ICP:
    """Create a demo ICP."""
    return ICP(
        industry=["SaaS", "DevOps", "Cloud Infrastructure"],
        company_size_range="10-200",
        locations=["India", "US", "Singapore"],
        target_roles=["CTO", "VP Engineering", "Head of DevOps"],
        keywords=["devops", "ci/cd", "kubernetes", "cloud", "automation", "monitoring"],
        exclusions=["consulting", "outsourcing", "body shopping"],
        summary="Mid-sized SaaS companies with engineering teams that need DevOps automation tools.",
    )


def mock_score_lead(lead: CleanLead, icp: ICP, index: int) -> ScoredLead:
    """Deterministically score a lead without LLM (for demo purposes)."""
    # Simple heuristic scoring based on keyword matching
    desc = (lead.description or "").lower()
    name = lead.company_name.lower()

    industry_score = 0
    for kw in ["saas", "cloud", "devops", "infrastructure", "platform"]:
        if kw in desc or kw in name:
            industry_score += 4
    industry_score = min(industry_score, 20)

    size_score = 15  # Assume startup-sized

    location = (lead.location or "").lower()
    location_score = 0
    for loc in ["india", "bangalore", "mumbai", "us", "san francisco", "singapore"]:
        if loc in location:
            location_score = 18
            break

    role_score = 12  # Moderate default

    signal_score = 0
    for kw in icp.keywords:
        if kw.lower() in desc:
            signal_score += 3
    signal_score = min(signal_score, 20)

    # Penalty for exclusions
    for excl in icp.exclusions:
        if excl.lower() in desc or excl.lower() in name:
            industry_score = max(0, industry_score - 15)
            signal_score = max(0, signal_score - 10)

    scores = ICPScores(
        industry_score=industry_score,
        size_score=size_score,
        location_score=location_score,
        role_score=role_score,
        signal_score=signal_score,
    )

    total = scores.total

    # Generate reason
    reasons = []
    if industry_score >= 15:
        reasons.append("strong industry match")
    elif industry_score >= 8:
        reasons.append("moderate industry match")
    else:
        reasons.append("weak industry match")

    if location_score >= 15:
        reasons.append("target location")
    if signal_score >= 10:
        reasons.append("multiple keyword signals")

    for excl in icp.exclusions:
        if excl.lower() in desc.lower() or excl.lower() in name:
            reasons.append(f"excluded: {excl}")

    reason = f"Score {total}/100: {', '.join(reasons)}."

    return ScoredLead(
        company_name=lead.company_name,
        domain=lead.domain,
        website_url=lead.website_url,
        emails=[
            EmailResult(
                email=e,
                status=EmailStatus.UNKNOWN,
                method="mock",
            )
            for e in lead.emails
        ],
        phone=lead.phone,
        description=lead.description,
        location=lead.location,
        industry="SaaS / DevOps" if industry_score > 10 else "Other",
        product_description=lead.description,
        size_guess="10-50",
        founder_name=None,
        contact_email=lead.emails[0] if lead.emails else None,
        icp_scores=scores,
        total_score=total,
        reason=reason,
        sources=[
            FieldProvenance(
                source_url=s.source_url if hasattr(s, "source_url") else "mock",
                collected_at=datetime.now(timezone.utc),
            )
            for s in (lead.sources if hasattr(lead, "sources") and lead.sources else [])
        ] or [
            FieldProvenance(source_url="mock://demo", collected_at=datetime.now(timezone.utc))
        ],
    )


def run_demo():
    """Run the demo pipeline offline."""
    print("=" * 60)
    print("🎯 LeadPilot AI — DEMO RUN (offline, mocked)")
    print("=" * 60)

    # Step 1: Load mock data
    print("\n📥 Loading 10 demo leads...")
    raw_leads = load_mock_leads()
    icp = mock_icp()

    print(f"   ICP: {icp.summary}")
    print(f"   Industries: {icp.industry}")
    print(f"   Locations: {icp.locations}")

    # Step 2: Deduplicate
    print("\n🔄 Deduplicating...")
    result = clean_dedupe({"raw_leads": raw_leads})
    clean_leads = result["clean_leads"]
    print(f"   {len(raw_leads)} raw → {len(clean_leads)} clean leads")

    # Step 3: Score (mock scoring)
    print("\n📊 Scoring leads against ICP...")
    scored_leads = [
        mock_score_lead(lead, icp, i)
        for i, lead in enumerate(clean_leads)
    ]
    scored_leads.sort(key=lambda l: l.total_score, reverse=True)

    # Step 4: Display results
    print("\n📋 RANKED LEADS:")
    print("-" * 60)
    for i, lead in enumerate(scored_leads, 1):
        email_str = ""
        if lead.emails:
            email_str = f" | ✉️ {lead.emails[0].email}"
        print(
            f"  {i:2d}. [{lead.total_score:3d}/100] {lead.company_name}"
            f" | {lead.location or 'N/A'}"
            f"{email_str}"
        )
        print(f"      → {lead.reason}")

    # Step 5: Export to Excel
    print("\n📁 Exporting to Excel...")
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    excel_path = export_to_excel(scored_leads, output_dir / "demo_leads.xlsx")
    print(f"   ✅ Exported to {excel_path}")

    # Step 6: Show DataFrame
    print("\n📊 DataFrame preview:")
    df = leads_to_dataframe(scored_leads)
    print(df[["Rank", "Company", "Score", "Industry", "Location"]].to_string(index=False))

    print("\n" + "=" * 60)
    print("✅ Demo complete! Check data/demo_leads.xlsx")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
