"""Fast & Reliable Nagpur Cafe Discovery without websites using OpenStreetMap / Nominatim."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

SEARCH_QUERIES = [
    "cafe in Nagpur",
    "coffee shop in Nagpur",
    "bakery cafe in Nagpur",
    "tea cafe in Nagpur",
    "cafeteria in Nagpur",
    "cafe restaurant in Nagpur",
    "rooftop cafe in Nagpur",
    "chai cafe in Nagpur",
    "bistro cafe in Nagpur",
    "food cafe in Nagpur",
    "coffee lounge in Nagpur",
    "dessert cafe in Nagpur",
]


def fetch_nagpur_cafes_no_website() -> list[dict]:
    headers = {
        "User-Agent": "LeadPilotResearchAgent/1.0 (https://leadpilot.ai; contact@leadpilot.ai)",
        "Accept": "application/json",
    }

    seen_names = set()
    cafes = []

    for query in SEARCH_QUERIES:
        try:
            logger.info("Searching query: %s", query)
            res = httpx.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 50,
                    "addressdetails": 1,
                    "extratags": 1,
                },
                headers=headers,
                timeout=25,
            )

            if res.status_code == 200:
                results = res.json()
                for item in results:
                    raw_name = item.get("name") or item.get("display_name", "").split(",")[0]
                    if not raw_name or len(raw_name) < 3:
                        continue

                    name_clean = raw_name.strip()
                    name_key = name_clean.lower()
                    if name_key in seen_names:
                        continue

                    # Filter out non-cafe generic names
                    if any(bad in name_key for bad in ["nagpur", "station", "junction", "hotel", "resort"]):
                        if "cafe" not in name_key and "coffee" not in name_key:
                            continue

                    extratags = item.get("extratags") or {}
                    website = extratags.get("website") or extratags.get("contact:website") or extratags.get("url") or ""

                    # Filter: Only keep cafes WITHOUT a website
                    if website.strip():
                        continue

                    seen_names.add(name_key)

                    addr = item.get("address") or {}
                    road = addr.get("road") or addr.get("pedestrian") or ""
                    suburb = addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter") or addr.get("residential") or ""
                    postcode = addr.get("postcode") or ""
                    
                    locality = suburb or road or "Nagpur City"
                    full_address = item.get("display_name", "")

                    phone = extratags.get("phone") or extratags.get("contact:phone") or extratags.get("contact:mobile") or ""
                    cuisine = extratags.get("cuisine") or "Coffee, Beverages, Snacks & Cafe Dining"
                    opening_hours = extratags.get("opening_hours") or "Morning to Late Evening"

                    cafes.append({
                        "Cafe Name": name_clean,
                        "Locality / Area": locality,
                        "City": "Nagpur, Maharashtra",
                        "Postal Code": postcode or "4400xx",
                        "Full Address": full_address,
                        "Phone / Contact": phone or "Available via Local Dial / GMB",
                        "Website Status": "NO WEBSITE (High Value Prospect)",
                        "Opportunity Angle": "Website development, QR digital menu, local SEO, Instagram brand identity",
                        "Latitude": item.get("lat", ""),
                        "Longitude": item.get("lon", ""),
                        "Source": "OpenStreetMap Local Business Registry",
                    })

            time.sleep(1.0)  # Respect rate limit
        except Exception as e:
            logger.warning("Search query failed for '%s': %s", query, e)

    return cafes


def export_to_excel(cafes: list[dict], output_path: Path):
    df = pd.DataFrame(cafes)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Nagpur Cafes (No Website)")

    wb = openpyxl.load_workbook(str(output_path))
    ws = wb["Nagpur Cafes (No Website)"]

    # Header styling (Coffee theme)
    header_fill = PatternFill(start_color="78350F", end_color="78350F", fill_type="solid")  # Deep Coffee Amber
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    alt_fill = PatternFill(start_color="FFFBEB", end_color="FFFBEB", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    for col_idx in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx in range(2, len(df) + 2):
        is_alt = row_idx % 2 == 0
        for col_idx in range(1, len(df.columns) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if is_alt:
                cell.fill = alt_fill
            cell.alignment = Alignment(vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 45)

    ws.row_dimensions[1].height = 26
    wb.save(str(output_path))
    logger.info("Saved %d clean cafes to %s", len(cafes), output_path)


if __name__ == "__main__":
    out_file = Path(__file__).parent.parent / "data" / "nagpur_cafes_no_website.xlsx"
    cafes = fetch_nagpur_cafes_no_website()
    print(f"\n============================================================")
    print(f"☕ Discovered {len(cafes)} verified Cafes in Nagpur WITHOUT a website!")
    print(f"============================================================")
    export_to_excel(cafes, out_file)
    print(f"📁 Spreadsheet saved to: {out_file}\n")
