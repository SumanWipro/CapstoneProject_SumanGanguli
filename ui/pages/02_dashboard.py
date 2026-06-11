"""
ui/pages/02_dashboard.py
=========================
Streamlit page: Observability Dashboard.

Responsibilities:
- Load all audit records from audit/logs/*.jsonl (all dates or filtered)
- Display KPI metrics: total, approval rate, rejection rate, review rate,
  average confidence score
- Render verdict distribution pie chart
- Render confidence score histogram
- Render risk score distribution chart
- Show full audit log as an interactive, filterable dataframe
- Auto-refresh every 30 seconds

Design decision — reads audit files directly:
    No database required. utils.audit.read_audit_records() reads JSONL
    files written by the Compliance Agent. st.cache_data(ttl=30) prevents
    re-reading on every Streamlit interaction while keeping data fresh.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import json
from datetime import datetime, timedelta, timezone

import streamlit as st

from config.settings import get_settings

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def _load_all_records(days_back: int = 7) -> list[dict]:
    """
    Load audit records for the last N days from audit/logs/.

    Returns:
        List of record dicts, newest first.
    """
    audit_dir = Path(settings.audit_log_dir)
    if not audit_dir.exists():
        return []

    records = []
    today = datetime.now(timezone.utc).date()
    for i in range(days_back):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        log_file = audit_dir / f"{date_str}.jsonl"
        if log_file.exists():
            with open(log_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

    # Newest first
    records.sort(key=lambda r: r.get("server_timestamp_utc", ""), reverse=True)
    return records


def _safe_pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0%"
    return f"{numerator/denominator:.0%}"


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("📊 Observability Dashboard")
st.caption("Real-time view of loan decisions from audit/logs/ — auto-refreshes every 30 seconds.")
st.divider()

# Sidebar controls
with st.sidebar:
    st.header("Filters")
    days_back = st.slider("Days to show", min_value=1, max_value=30, value=7)
    verdict_filter = st.multiselect(
        "Filter by Verdict",
        options=["APPROVED", "REJECTED", "REVIEW_REQUIRED"],
        default=["APPROVED", "REJECTED", "REVIEW_REQUIRED"],
    )
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
all_records = _load_all_records(days_back=days_back)

# Apply verdict filter
records = [r for r in all_records if r.get("verdict") in verdict_filter]

total      = len(records)
approved   = sum(1 for r in records if r.get("verdict") == "APPROVED")
rejected   = sum(1 for r in records if r.get("verdict") == "REJECTED")
review     = sum(1 for r in records if r.get("verdict") == "REVIEW_REQUIRED")
avg_conf   = sum(r.get("confidence_score", 0) for r in records) / total if total else 0
avg_risk   = sum(r.get("risk_score", 0) or 0 for r in records) / total if total else 0

# ---------------------------------------------------------------------------
# KPI Metrics
# ---------------------------------------------------------------------------
st.subheader("Key Metrics")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total Applications", total)
m2.metric("Approved",           f"{approved} ({_safe_pct(approved, total)})")
m3.metric("Rejected",           f"{rejected} ({_safe_pct(rejected, total)})")
m4.metric("Review Required",    f"{review} ({_safe_pct(review, total)})")
m5.metric("Avg Confidence",     f"{avg_conf:.0%}")
m6.metric("Avg Risk Score",     f"{avg_risk:.1f}/100")

st.divider()

if total == 0:
    st.info(
        "No audit records found for the selected period. "
        "Submit a loan application on the Loan Application page, "
        "or check that audit/logs/ exists.",
        icon="ℹ️",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Charts row
# ---------------------------------------------------------------------------
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

chart_col1, chart_col2, chart_col3 = st.columns(3)

with chart_col1:
    st.subheader("Verdict Distribution")
    verdict_counts = {"APPROVED": approved, "REJECTED": rejected, "REVIEW_REQUIRED": review}
    if HAS_PLOTLY:
        fig = px.pie(
            names=list(verdict_counts.keys()),
            values=list(verdict_counts.values()),
            color=list(verdict_counts.keys()),
            color_discrete_map={
                "APPROVED": "#22c55e",
                "REJECTED": "#ef4444",
                "REVIEW_REQUIRED": "#f97316",
            },
            hole=0.4,
        )
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Fallback: plain metrics
        for v, c in verdict_counts.items():
            st.metric(v, c)

with chart_col2:
    st.subheader("Confidence Score Distribution")
    confidence_values = [r.get("confidence_score", 0) for r in records if r.get("confidence_score") is not None]
    if HAS_PLOTLY and confidence_values:
        fig2 = px.histogram(
            x=confidence_values,
            nbins=20,
            labels={"x": "Confidence Score"},
            color_discrete_sequence=["#6366f1"],
        )
        fig2.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            xaxis_title="Confidence Score",
            yaxis_title="Count",
        )
        st.plotly_chart(fig2, use_container_width=True)
    elif confidence_values:
        st.bar_chart(confidence_values)

with chart_col3:
    st.subheader("Risk Score Distribution")
    risk_values = [r.get("risk_score") for r in records if r.get("risk_score") is not None]
    if HAS_PLOTLY and risk_values:
        fig3 = px.histogram(
            x=risk_values,
            nbins=20,
            labels={"x": "Risk Score"},
            color_discrete_sequence=["#f43f5e"],
        )
        fig3.add_vline(x=40, line_dash="dash", line_color="green",
                       annotation_text="Approve <40")
        fig3.add_vline(x=70, line_dash="dash", line_color="red",
                       annotation_text="Reject >70")
        fig3.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig3, use_container_width=True)
    elif risk_values:
        st.bar_chart(risk_values)

st.divider()

# ---------------------------------------------------------------------------
# Credit band breakdown
# ---------------------------------------------------------------------------
st.subheader("Credit Band Breakdown")

band_counts: dict[str, int] = {}
for r in records:
    band = r.get("credit_band", "unknown")
    band_counts[band] = band_counts.get(band, 0) + 1

band_order = ["excellent", "good", "fair", "poor", "unknown"]
bc1, bc2, bc3, bc4 = st.columns(4)
for col, band in zip([bc1, bc2, bc3, bc4], ["excellent", "good", "fair", "poor"]):
    col.metric(band.title(), band_counts.get(band, 0))

st.divider()

# ---------------------------------------------------------------------------
# Audit log table
# ---------------------------------------------------------------------------
st.subheader(f"Audit Log — Last {days_back} Days ({total} records)")

# Build display rows
display_cols = [
    "server_timestamp_utc", "case_id", "applicant_id", "verdict",
    "confidence_score", "risk_score", "credit_band", "dti",
    "employment_band",
]

table_rows = []
for r in records:
    row = {col: r.get(col) for col in display_cols}
    # Format timestamp
    ts = row.get("server_timestamp_utc", "")
    if ts:
        try:
            row["server_timestamp_utc"] = ts[:19].replace("T", " ")
        except Exception:
            pass
    # Round floats
    if row.get("confidence_score") is not None:
        row["confidence_score"] = round(float(row["confidence_score"]), 2)
    if row.get("risk_score") is not None:
        row["risk_score"] = round(float(row["risk_score"]), 1)
    if row.get("dti") is not None:
        row["dti"] = round(float(row["dti"]), 4)
    table_rows.append(row)

if table_rows:
    st.dataframe(
        table_rows,
        use_container_width=True,
        height=400,
        column_config={
            "server_timestamp_utc": st.column_config.TextColumn("Timestamp"),
            "case_id":              st.column_config.TextColumn("Case ID"),
            "applicant_id":         st.column_config.TextColumn("Applicant ID"),
            "verdict":              st.column_config.TextColumn("Verdict"),
            "confidence_score":     st.column_config.NumberColumn("Confidence", format="%.2f"),
            "risk_score":           st.column_config.NumberColumn("Risk Score", format="%.1f"),
            "credit_band":          st.column_config.TextColumn("Credit Band"),
            "dti":                  st.column_config.NumberColumn("DTI", format="%.4f"),
            "employment_band":      st.column_config.TextColumn("Employment Band"),
        },
    )

    # Record details expander
    st.divider()
    st.subheader("Record Detail")
    case_ids = [r.get("case_id", "—") for r in records]
    selected_case = st.selectbox("Select Case ID to inspect", options=case_ids)
    if selected_case:
        selected_record = next((r for r in records if r.get("case_id") == selected_case), None)
        if selected_record:
            with st.expander(f"Full Record — {selected_case}", expanded=True):
                st.json(selected_record)
