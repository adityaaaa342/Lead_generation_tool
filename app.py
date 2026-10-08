"""LeadPilot AI — Streamlit Dashboard.

Run with: streamlit run app.py
"""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from leadpilot.ui.dashboard import (
    load_leads,
    load_runs,
    render_filters,
    render_industry_breakdown,
    render_lead_table,
    render_metrics,
    render_score_distribution,
)
from leadpilot.graph import run_pipeline
from leadpilot.config import get_settings

# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LeadPilot AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    }
    .main .block-container {
        padding-top: 2rem;
    }
    h1 {
        background: linear-gradient(90deg, #667eea, #764ba2);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem !important;
    }
    .stMetric {
        background: rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 1rem;
        border: 1px solid rgba(255,255,255,0.1);
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────

st.title("🎯 LeadPilot AI")
st.markdown("*Lead discovery, enrichment and scoring — powered by AI*")

# ── Sidebar: Run Selection ───────────────────────────────────────────────────

runs = load_runs()

if runs:
    st.sidebar.header("📋 Pipeline Runs")
    run_options = {
        f"{r['id']} — {r['brief'][:40]}... ({r['lead_count']} leads)": r["id"]
        for r in runs
    }
    selected_run_label = st.sidebar.selectbox(
        "Select Run", list(run_options.keys())
    )
    selected_run_id = run_options[selected_run_label]
else:
    selected_run_id = None

# ── New Run ──────────────────────────────────────────────────────────────────

st.sidebar.markdown("---")
st.sidebar.header("🚀 New Discovery Run")

brief = st.sidebar.text_area(
    "Business Description",
    placeholder="We sell DevOps automation tools to mid-sized SaaS companies...",
    height=100,
)
limit = st.sidebar.slider("Max Leads", 10, 200, 50)

if st.sidebar.button("🔍 Start Discovery", type="primary"):
    if brief:
        with st.spinner("🔄 Running LeadPilot pipeline... This may take a few minutes."):
            try:
                settings = get_settings()
                result = run_pipeline(brief=brief, limit=limit, settings=settings)
                scored_leads = result.get("scored_leads", [])
                st.sidebar.success(f"✅ Found {len(scored_leads)} leads!")
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"❌ Pipeline failed: {exc}")
    else:
        st.sidebar.warning("Please enter a business description")

# ── Main Content ─────────────────────────────────────────────────────────────

if selected_run_id:
    df = load_leads(run_id=selected_run_id)

    if not df.empty:
        # Apply filters
        df = render_filters(df)

        # Metrics
        render_metrics(df)

        st.markdown("---")

        # Tabs
        tab1, tab2, tab3 = st.tabs(["📋 Lead Table", "📊 Analytics", "📥 Export"])

        with tab1:
            render_lead_table(df)

        with tab2:
            col1, col2 = st.columns(2)
            with col1:
                render_score_distribution(df)
            with col2:
                render_industry_breakdown(df)

        with tab3:
            settings = get_settings()
            excel_path = settings.cache_dir / "leads.xlsx"

            if excel_path.exists():
                with open(excel_path, "rb") as f:
                    st.download_button(
                        label="📥 Download leads.xlsx",
                        data=f,
                        file_name="leads.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            else:
                st.info("No Excel export available yet. Run the pipeline first.")
    else:
        st.info("No leads found for this run. Try running a new discovery.")
else:
    st.info(
        "👋 Welcome to LeadPilot AI! "
        "Start a new discovery run from the sidebar, or select a previous run."
    )
