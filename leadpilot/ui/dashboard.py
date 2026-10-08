"""Streamlit dashboard components for LeadPilot AI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from leadpilot.config import get_settings
from leadpilot.storage.database import LeadDatabase


def load_leads(run_id: str | None = None, min_score: int = 0) -> pd.DataFrame:
    """Load leads from the database into a DataFrame."""
    settings = get_settings()
    db = LeadDatabase(settings.cache_dir / "leads.db")
    leads = db.get_leads(run_id=run_id, min_score=min_score, limit=500)

    if not leads:
        return pd.DataFrame()

    df = pd.DataFrame(leads)

    # Parse JSON fields
    for col in ["icp_scores_json", "emails_json", "sources_json"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: json.loads(x) if x else {})

    return df


def load_runs() -> list[dict[str, Any]]:
    """Load all pipeline runs."""
    settings = get_settings()
    db = LeadDatabase(settings.cache_dir / "leads.db")
    return db.get_runs()


def render_metrics(df: pd.DataFrame) -> None:
    """Render summary metrics."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Leads", len(df))
    with col2:
        avg_score = df["total_score"].mean() if not df.empty else 0
        st.metric("Avg Score", f"{avg_score:.0f}")
    with col3:
        high_quality = len(df[df["total_score"] >= 70]) if not df.empty else 0
        st.metric("High Quality (≥70)", high_quality)
    with col4:
        industries = df["industry"].nunique() if not df.empty and "industry" in df.columns else 0
        st.metric("Industries", industries)


def render_lead_table(df: pd.DataFrame) -> None:
    """Render the lead table with key columns."""
    display_cols = [
        "company_name", "total_score", "reason", "industry",
        "size_guess", "location", "founder_name", "contact_email",
        "domain", "website_url",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    if available_cols:
        st.dataframe(
            df[available_cols].rename(columns={
                "company_name": "Company",
                "total_score": "Score",
                "reason": "Reason",
                "industry": "Industry",
                "size_guess": "Size",
                "location": "Location",
                "founder_name": "Founder",
                "contact_email": "Email",
                "domain": "Domain",
                "website_url": "Website",
            }),
            use_container_width=True,
            height=500,
        )


def render_score_distribution(df: pd.DataFrame) -> None:
    """Render score distribution chart."""
    if df.empty or "total_score" not in df.columns:
        return

    st.subheader("📊 Score Distribution")
    chart_data = df["total_score"].value_counts().sort_index()
    st.bar_chart(chart_data)


def render_industry_breakdown(df: pd.DataFrame) -> None:
    """Render industry breakdown chart."""
    if df.empty or "industry" not in df.columns:
        return

    st.subheader("🏭 Industry Breakdown")
    industry_counts = df["industry"].value_counts().head(10)
    if not industry_counts.empty:
        st.bar_chart(industry_counts)


def render_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Render sidebar filters and return filtered DataFrame."""
    st.sidebar.header("🔍 Filters")

    # Score filter
    if not df.empty and "total_score" in df.columns:
        min_score = st.sidebar.slider(
            "Minimum Score",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
        )
        df = df[df["total_score"] >= min_score]

    # Industry filter
    if not df.empty and "industry" in df.columns:
        industries = ["All"] + sorted(df["industry"].dropna().unique().tolist())
        selected_industry = st.sidebar.selectbox("Industry", industries)
        if selected_industry != "All":
            df = df[df["industry"] == selected_industry]

    # Location filter
    if not df.empty and "location" in df.columns:
        locations = ["All"] + sorted(df["location"].dropna().unique().tolist())
        selected_location = st.sidebar.selectbox("Location", locations)
        if selected_location != "All":
            df = df[df["location"] == selected_location]

    return df
