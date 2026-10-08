"""Node 8: Export — save leads to SQLite and generate Excel file."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from leadpilot.config import Settings, get_settings
from leadpilot.models import ScoredLead, PipelineState
from leadpilot.storage.database import LeadDatabase

logger = logging.getLogger(__name__)


def leads_to_dataframe(leads: list[ScoredLead]) -> pd.DataFrame:
    """Convert scored leads to a pandas DataFrame for export."""
    rows = []
    for lead in leads:
        # Get best email
        best_email = ""
        email_status = ""
        if lead.emails:
            # Prefer valid emails, then risky, then unknown
            sorted_emails = sorted(
                lead.emails,
                key=lambda e: {"valid": 0, "risky": 1, "unknown": 2, "invalid": 3}.get(
                    e.status.value, 4
                ),
            )
            best_email = sorted_emails[0].email
            email_status = sorted_emails[0].status.value

        rows.append({
            "Rank": 0,  # Will be set after sorting
            "Company": lead.company_name,
            "Score": lead.total_score,
            "Reason": lead.reason,
            "Industry": lead.industry or "",
            "Size": lead.size_guess or "",
            "Location": lead.location or "",
            "Founder": lead.founder_name or "",
            "Email": best_email,
            "Email Status": email_status,
            "Phone": lead.phone or "",
            "Domain": lead.domain or "",
            "Website": lead.website_url or "",
            "Product": lead.product_description or "",
            "Industry Score": lead.icp_scores.industry_score,
            "Size Score": lead.icp_scores.size_score,
            "Location Score": lead.icp_scores.location_score,
            "Role Score": lead.icp_scores.role_score,
            "Signal Score": lead.icp_scores.signal_score,
            "Sources": ", ".join(s.source_url for s in lead.sources) if lead.sources else "",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Score", ascending=False).reset_index(drop=True)
        df["Rank"] = range(1, len(df) + 1)

    return df


def export_to_excel(
    leads: list[ScoredLead],
    output_path: Path | str = "leads.xlsx",
) -> Path:
    """Export scored leads to an Excel file."""
    output_path = Path(output_path)
    df = leads_to_dataframe(leads)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Leads", index=False)

        # Auto-adjust column widths
        worksheet = writer.sheets["Leads"]
        for idx, col in enumerate(df.columns):
            max_len = max(
                df[col].astype(str).map(len).max() if not df.empty else 0,
                len(col),
            )
            worksheet.column_dimensions[
                chr(65 + idx) if idx < 26 else chr(64 + idx // 26) + chr(65 + idx % 26)
            ].width = min(max_len + 2, 50)

    logger.info("Exported %d leads to %s", len(leads), output_path)
    return output_path


def export(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: Export scored leads to SQLite and Excel.

    Args:
        state: Pipeline state dict containing 'scored_leads', 'brief', 'icp'.

    Returns:
        Updated state dict with export metadata.
    """
    scored_leads: list[ScoredLead] = state["scored_leads"]
    brief = state.get("brief", "")
    icp = state.get("icp")
    errors = state.get("errors", [])

    settings = get_settings()
    run_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    logger.info("Exporting %d scored leads (run_id=%s)", len(scored_leads), run_id)

    # 1. Save to SQLite
    db = LeadDatabase(settings.cache_dir / "leads.db")
    saved_count = db.save_leads(scored_leads, run_id)
    db.save_run(
        run_id=run_id,
        brief=brief,
        icp_json=icp.model_dump_json() if icp else None,
        started_at=state.get("started_at", now),
        completed_at=now,
        lead_count=saved_count,
        errors=errors,
    )

    # 2. Export to Excel
    excel_path = export_to_excel(scored_leads, settings.cache_dir / "leads.xlsx")

    logger.info(
        "Export complete: %d leads saved to DB, Excel at %s",
        saved_count,
        excel_path,
    )

    return {
        "completed_at": datetime.now(timezone.utc),
        "errors": errors,
    }
