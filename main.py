"""LeadPilot AI — CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """CLI entry point: python main.py --brief "..." --limit 50"""
    parser = argparse.ArgumentParser(
        prog="leadpilot",
        description="LeadPilot AI: Lead discovery, enrichment and scoring agent",
    )
    parser.add_argument(
        "--brief",
        required=True,
        help="Business description / what you sell and who you sell to",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of leads to collect (default: 50)",
    )
    parser.add_argument(
        "--skip-personal-emails",
        action="store_true",
        help="Skip personal email collection (only generic emails)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output Excel file path (default: data/leads.xlsx)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Load .env file
    load_dotenv()

    # Setup logging
    from leadpilot.config import setup_logging, get_settings

    settings = get_settings(
        log_level=args.log_level,
        skip_personal_emails=args.skip_personal_emails,
    )
    setup_logging(settings)

    logger = logging.getLogger("leadpilot")
    logger.info("=" * 60)
    logger.info("LeadPilot AI — Starting pipeline")
    logger.info("Brief: %s", args.brief)
    logger.info("Limit: %d leads", args.limit)
    logger.info("LLM: %s @ %s", settings.llm_model, settings.llm_base_url)
    logger.info("=" * 60)

    # Run the pipeline
    from leadpilot.graph import run_pipeline

    try:
        result = run_pipeline(
            brief=args.brief,
            limit=args.limit,
            settings=settings,
        )

        scored_leads = result.get("scored_leads", [])
        errors = result.get("errors", [])

        # Print summary
        print("\n" + "=" * 60)
        print(f"✅ LeadPilot AI — Pipeline Complete")
        print(f"   Leads found: {len(scored_leads)}")
        if scored_leads:
            print(f"   Top score:   {scored_leads[0].total_score}/100")
            print(f"   Top lead:    {scored_leads[0].company_name}")
        if errors:
            print(f"   ⚠️  Errors:   {len(errors)}")

        # Print top 10
        print("\n📊 Top Leads:")
        print("-" * 60)
        for i, lead in enumerate(scored_leads[:10], 1):
            email_str = ""
            if lead.emails:
                valid_emails = [e for e in lead.emails if e.status.value == "valid"]
                if valid_emails:
                    email_str = f" | ✉️ {valid_emails[0].email}"
            print(
                f"  {i:2d}. [{lead.total_score:3d}/100] {lead.company_name}"
                f" | {lead.industry or 'N/A'}"
                f" | {lead.location or 'N/A'}"
                f"{email_str}"
            )
            print(f"      → {lead.reason}")

        print("-" * 60)
        print(f"📁 Full results: {settings.cache_dir / 'leads.xlsx'}")
        print(f"🗄️  Database:    {settings.cache_dir / 'leads.db'}")
        print(f"🌐 Dashboard:   streamlit run app.py")

    except KeyboardInterrupt:
        print("\n⚠️ Pipeline interrupted by user")
        sys.exit(1)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        print(f"\n❌ Pipeline failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
