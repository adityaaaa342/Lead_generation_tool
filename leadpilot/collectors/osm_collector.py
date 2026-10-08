"""OpenStreetMap Overpass API collector for local businesses."""

from __future__ import annotations

import json
import logging
from typing import Any

from leadpilot.collectors.base import BaseCollector
from leadpilot.models import ICP, RawLead

logger = logging.getLogger(__name__)

OVERPASS_API = "https://overpass-api.de/api/interpreter"

# Map ICP industries to OSM tags
INDUSTRY_TO_OSM_TAGS: dict[str, list[str]] = {
    "restaurant": ['["amenity"="restaurant"]'],
    "cafe": ['["amenity"="cafe"]'],
    "salon": ['["shop"="hairdresser"]', '["shop"="beauty"]'],
    "beauty": ['["shop"="beauty"]', '["shop"="hairdresser"]'],
    "fitness": ['["leisure"="fitness_centre"]'],
    "gym": ['["leisure"="fitness_centre"]'],
    "real estate": ['["office"="estate_agent"]'],
    "hotel": ['["tourism"="hotel"]'],
    "clinic": ['["amenity"="clinic"]', '["amenity"="dentist"]'],
    "dental": ['["amenity"="dentist"]'],
    "law": ['["office"="lawyer"]'],
    "legal": ['["office"="lawyer"]'],
    "consulting": ['["office"="consulting"]'],
    "agency": ['["office"="advertising"]', '["office"="company"]'],
    "marketing": ['["office"="advertising"]'],
    "design": ['["office"="graphic_design"]', '["office"="company"]'],
    "retail": ['["shop"]'],
    "tech": ['["office"="it"]', '["office"="company"]'],
    "saas": ['["office"="it"]', '["office"="company"]'],
    "fintech": ['["office"="financial"]', '["amenity"="bank"]'],
    "healthcare": ['["amenity"="clinic"]', '["amenity"="hospital"]'],
    "education": ['["amenity"="school"]', '["amenity"="university"]'],
    "coworking": ['["amenity"="coworking_space"]'],
    "startup": ['["office"="company"]', '["amenity"="coworking_space"]'],
    "manufacturing": ['["landuse"="industrial"]', '["man_made"="works"]'],
    "logistics": ['["office"="logistics"]', '["amenity"="post_office"]'],
}

# Common city bounding boxes (south, west, north, east)
CITY_BBOXES: dict[str, str] = {
    "santa monica": "34.00,-118.53,34.05,-118.45",
    "los angeles": "33.70,-118.67,34.34,-118.15",
    "california": "33.70,-118.67,34.34,-118.15",
    "bangalore": "12.85,77.45,13.15,77.75",
    "mumbai": "18.85,72.75,19.30,73.05",
    "delhi": "28.40,76.85,28.85,77.35",
    "hyderabad": "17.25,78.30,17.55,78.60",
    "pune": "18.40,73.75,18.65,74.00",
    "chennai": "12.90,80.10,13.20,80.35",
    "san francisco": "37.70,-122.52,37.82,-122.35",
    "new york": "40.65,-74.05,40.85,-73.85",
    "london": "51.40,-0.20,51.60,0.05",
    "singapore": "1.22,103.65,1.47,104.05",
}


class OSMCollector(BaseCollector):
    """Collect business leads from OpenStreetMap via the Overpass API."""

    SOURCE_NAME = "osm_collector"

    def collect(
        self,
        icp: ICP,
        params: dict[str, Any] | None = None,
        max_leads: int = 20,
    ) -> list[RawLead]:
        """Query Overpass for businesses matching ICP location and industry.

        Params can include:
            - bbox: explicit bounding box "south,west,north,east"
            - osm_tags: explicit Overpass tag filters
        """
        params = params or {}
        leads: list[RawLead] = []

        # Determine bounding boxes from ICP locations
        bboxes = self._resolve_bboxes(icp.locations, params.get("bbox"))
        osm_tags = params.get("osm_tags") or self._resolve_tags(icp.industry)

        for bbox in bboxes:
            if len(leads) >= max_leads:
                break

            for tag_filter in osm_tags:
                if len(leads) >= max_leads:
                    break

                query = self._build_query(bbox, tag_filter, max_leads - len(leads))
                logger.info("Overpass query for bbox=%s tag=%s", bbox, tag_filter)

                result = self.http.fetch(
                    OVERPASS_API,
                    method="GET",
                    params={"data": query},
                )

                if not result.ok:
                    logger.warning("Overpass API returned status %d", result.status_code)
                    continue

                try:
                    data = json.loads(result.text)
                    elements = data.get("elements", [])
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Failed to parse Overpass response: %s", exc)
                    continue

                for elem in elements:
                    lead = self._element_to_lead(elem, bbox)
                    if lead:
                        leads.append(lead)

        return leads[:max_leads]

    def _resolve_bboxes(
        self, locations: list[str], explicit_bbox: str | None
    ) -> list[str]:
        """Convert ICP locations to Overpass bounding boxes."""
        if explicit_bbox:
            return [explicit_bbox]

        bboxes = []
        for loc in locations:
            loc_lower = loc.lower().strip()
            for city, bbox in CITY_BBOXES.items():
                if city in loc_lower or loc_lower in city:
                    bboxes.append(bbox)
                    break

        return bboxes or ["12.85,77.45,13.15,77.75"]  # Default: Bangalore

    def _resolve_tags(self, industries: list[str]) -> list[str]:
        """Map ICP industries to OSM tag filters."""
        tags: list[str] = []
        for industry in industries:
            industry_lower = industry.lower()
            for key, tag_list in INDUSTRY_TO_OSM_TAGS.items():
                if key in industry_lower or industry_lower in key:
                    tags.extend(tag_list)
                    break

        return tags or ['["office"="company"]']  # Default fallback

    @staticmethod
    def _build_query(bbox: str, tag_filter: str, limit: int) -> str:
        """Build an Overpass QL query."""
        return f"""
        [out:json][timeout:30];
        (
          node{tag_filter}({bbox});
          way{tag_filter}({bbox});
        );
        out center tags {min(limit, 50)};
        """

    def _element_to_lead(self, element: dict, bbox: str) -> RawLead | None:
        """Convert an OSM element to a RawLead."""
        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("brand")

        if not name:
            return None

        # Extract contact info from OSM tags
        website = tags.get("website") or tags.get("contact:website")
        email = tags.get("email") or tags.get("contact:email")
        phone = tags.get("phone") or tags.get("contact:phone")

        domain = None
        if website:
            from urllib.parse import urlparse
            parsed = urlparse(website)
            domain = parsed.netloc.lower().removeprefix("www.") if parsed.netloc else None

        # Location from coordinates
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        address_parts = [
            tags.get("addr:street"),
            tags.get("addr:city"),
            tags.get("addr:state"),
            tags.get("addr:country"),
        ]
        location = ", ".join(p for p in address_parts if p) or (
            f"{lat}, {lon}" if lat and lon else None
        )

        return self._make_lead(
            company_name=name,
            domain=domain,
            website_url=website,
            emails=[email] if email else [],
            phone=phone,
            description=tags.get("description"),
            location=location,
            source_url=f"https://www.openstreetmap.org/node/{element.get('id', '')}",
            raw_data={"osm_tags": tags, "bbox": bbox},
        )
