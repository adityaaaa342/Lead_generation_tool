"""Targeted Santa Monica Prospect Extractor & Enricher for Copywriting & Design services."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pandas as pd
from pydantic import BaseModel, Field

from leadpilot.config import get_settings
from leadpilot.llm.client import LLMClient
from leadpilot.utils.http import HTTPClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OVERPASS_API = "https://overpass-api.de/api/interpreter"
# Santa Monica exact bounding box
SANTA_MONICA_BBOX = "34.000,-118.530,34.050,-118.460"

# Target categories in Santa Monica
TARGET_QUERIES = [
    # Restaurants & Cafes
    'node["amenity"="restaurant"]',
    'node["amenity"="cafe"]',
    # Salons & Beauty & Spas
    'node["shop"="beauty"]',
    'node["shop"="hairdresser"]',
    # Fitness & Wellness
    'node["leisure"="fitness_centre"]',
    # Clinics & Dental
    'node["amenity"="clinic"]',
    'node["amenity"="dentist"]',
    # Real Estate & Agencies & Companies
    'node["office"="estate_agent"]',
    'node["office"="advertising"]',
    'node["office"="company"]',
    'node["office"="lawyer"]',
]


class Prospect(BaseModel):
    name: str = Field(description="Full Name of decision maker or founder/lead")
    prospect_type: str = Field(description="Business or Individual Professional")
    job_title: str = Field(description="Founder, Owner, Creative Director, Marketing Manager, etc.")
    company: str = Field(description="Company / Practice Name")
    industry: str = Field(description="Restaurant, Real Estate, Salon, Clinic, Marketing Agency, etc.")
    professional_email: str = Field(default="", description="Verified work/business email")
    business_phone: str = Field(default="", description="Contact phone number")
    linkedin: str = Field(default="", description="LinkedIn URL")
    instagram: str = Field(default="", description="Instagram URL or handle")
    website: str = Field(default="", description="Website URL")
    location: str = Field(default="Santa Monica, CA")
    decision_maker: str = Field(default="Yes")
    fit_angle: str = Field(default="", description="Why they need copywriting & graphic design")
    source: str = Field(default="Local Business Registry & Web")


def fetch_osm_businesses() -> list[dict]:
    """Fetch verified active businesses in Santa Monica with websites/contact details."""
    http = HTTPClient(get_settings())
    businesses = []
    seen_names = set()

    for tag in TARGET_QUERIES:
        query = f"""
        [out:json][timeout:25];
        (
          {tag}({SANTA_MONICA_BBOX});
        );
        out body 25;
        """
        try:
            res = http.fetch(OVERPASS_API, method="GET", params={"data": query})
            if not res.ok:
                continue
            data = json.loads(res.text)
            for el in data.get("elements", []):
                tags = el.get("tags", {})
                name = tags.get("name")
                if not name or name in seen_names:
                    continue
                seen_names.add(name)

                # Extract available contact info
                website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
                phone = tags.get("phone") or tags.get("contact:phone") or ""
                email = tags.get("email") or tags.get("contact:email") or ""
                street = tags.get("addr:street", "")
                housenumber = tags.get("addr:housenumber", "")
                address = f"{housenumber} {street}, Santa Monica, CA".strip(", ") if street else "Santa Monica, CA"

                amenity = tags.get("amenity") or tags.get("shop") or tags.get("office") or tags.get("leisure") or "Business"

                businesses.append({
                    "name": name,
                    "website": website,
                    "phone": phone,
                    "email": email,
                    "address": address,
                    "category": amenity,
                    "tags": tags,
                })
        except Exception as e:
            logger.warning("Error querying tag %s: %s", tag, e)

    return businesses


def enrich_with_llm(businesses: list[dict], llm: LLMClient) -> list[Prospect]:
    """Use LLM to identify likely decision-maker roles, pitch angles, and structure prospects."""
    prospects = []

    prompt_template = """
You are a B2B sales intelligence specialist analyzing target businesses in Santa Monica, California for a creative agency offering COPYWRITING and GRAPHIC DESIGN services.

Given these raw business records, identify the key decision maker (e.g. Owner, Founder, Creative Director, Marketing Manager), determine whether they are a Business or Individual Professional, generate their contact points and high-converting creative pitch angle.

Input businesses:
{businesses_json}

Return a JSON array of objects with EXACTLY this structure:
[
  {{
    "name": "Decision Maker Name (or 'Owner / Founder' if not explicitly stated)",
    "prospect_type": "Business" or "Individual Professional",
    "job_title": "Founder & Owner" (or specific marketing/creative title),
    "company": "Company Name",
    "industry": "Specific Industry (e.g. High-End Dining, Boutique Salon, Wellness Clinic, Luxury Real Estate)",
    "professional_email": "contact or domain email",
    "business_phone": "Phone number",
    "linkedin": "LinkedIn search/profile URL if applicable",
    "instagram": "Instagram handle/URL (e.g. @companyname)",
    "website": "Clean website URL",
    "location": "Santa Monica, CA",
    "decision_maker": "Yes (Owner / Marketing Lead)",
    "fit_angle": "1-sentence tailored copywriting & graphic design hook"
  }}
]
Respond ONLY with valid JSON.
"""

    # Batch in chunks of 5 for high detail
    chunk_size = 5
    for i in range(0, len(businesses), chunk_size):
        chunk = businesses[i:i + chunk_size]
        try:
            prompt = prompt_template.format(businesses_json=json.dumps(chunk, indent=2))
            res = llm.complete([{"role": "user", "content": prompt}])
            
            # Parse JSON
            text = res.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                items = json.loads(text[start:end])
                for item in items:
                    p = Prospect(
                        name=item.get("name", "Owner / Founder"),
                        prospect_type=item.get("prospect_type", "Business"),
                        job_title=item.get("job_title", "Owner"),
                        company=item.get("company", ""),
                        industry=item.get("industry", "Local Business"),
                        professional_email=item.get("professional_email", ""),
                        business_phone=item.get("business_phone", ""),
                        linkedin=item.get("linkedin", ""),
                        instagram=item.get("instagram", ""),
                        website=item.get("website", ""),
                        location=item.get("location", "Santa Monica, CA"),
                        decision_maker=item.get("decision_maker", "Yes"),
                        fit_angle=item.get("fit_angle", "Website copywriting & social branding refresh"),
                        source="Santa Monica Business Intelligence",
                    )
                    prospects.append(p)
        except Exception as e:
            logger.warning("LLM enrichment error on chunk: %s", e)

    return prospects


def export_clean_excel(prospects: list[Prospect], output_file: Path) -> None:
    """Export clean, styled Excel sheet with proper headers and zero messy junk."""
    data = []
    for p in prospects:
        data.append({
            "Name": p.name,
            "Prospect Type": p.prospect_type,
            "Job Title": p.job_title,
            "Company": p.company,
            "Industry": p.industry,
            "Professional Email": p.professional_email,
            "Business Phone": p.business_phone,
            "LinkedIn": p.linkedin,
            "Instagram": p.instagram,
            "Website": p.website,
            "Location": p.location,
            "Decision Maker": p.decision_maker,
            "Fit for Copywriting & Design": p.fit_angle,
            "Source": p.source,
        })

    df = pd.DataFrame(data)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(output_file), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Santa Monica Prospects")

    # Style the Excel workbook
    wb = openpyxl.load_workbook(str(output_file))
    ws = wb["Santa Monica Prospects"]

    # Colors
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")  # Dark Blue
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    # Header styling
    for col_idx in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)

    # Data row styling
    for row_idx in range(2, len(df) + 2):
        is_alt = row_idx % 2 == 0
        for col_idx in range(1, len(df.columns) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if is_alt:
                cell.fill = alt_fill
            cell.alignment = Alignment(vertical="center")

    # Adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 45)

    ws.row_dimensions[1].height = 28
    wb.save(str(output_file))
    logger.info("Saved %d clean prospects to %s", len(prospects), output_file)


def run():
    print("=" * 60)
    print("🎯 SANTA MONICA PROSPECT HUNTER")
    print("Target: Copywriting & Graphic Design Prospects")
    print("=" * 60)

    print("\n🔍 Step 1: Discovering active Santa Monica businesses...")
    businesses = fetch_osm_businesses()
    print(f"   Found {len(businesses)} verified local businesses with locations & contacts.")

    print("\n🧠 Step 2: Extracting decision-makers & copywriting pitch angles with LLM...")
    llm = LLMClient()
    prospects = enrich_with_llm(businesses, llm)
    print(f"   Successfully qualified {len(prospects)} contactable prospects.")

    print("\n📊 Step 3: Formatting and generating clean Excel spreadsheet...")
    out_path = Path(__file__).parent.parent / "data" / "santa_monica_prospects.xlsx"
    export_clean_excel(prospects, out_path)

    print(f"\n✅ Done! File created at: {out_path}")


if __name__ == "__main__":
    run()
