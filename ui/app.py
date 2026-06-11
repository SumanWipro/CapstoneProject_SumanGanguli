"""
ui/app.py
=========
Streamlit multi-page application entry point for the Loan Approval System.

Responsibilities:
- Configure global page layout (must be first Streamlit call)
- Initialise session state keys shared across all pages
- Render the Home landing page with system status panel
- Streamlit auto-discovers ui/pages/*.py as additional navigation pages

Run with:
    streamlit run ui/app.py --server.port 8501
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import streamlit as st

from config.settings import get_settings

# ---------------------------------------------------------------------------
# Page config — MUST be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Loan Approval System",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()
API_BASE = settings.fastapi_base_url


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "last_decision":       None,   # dict — last LoanDecisionResponse
    "last_request":        None,   # dict — last LoanApplicationRequest fields
    "application_history": [],     # list[dict] — all submissions this session
    "pipeline_trace":      [],     # list[dict] — node execution trace
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Helper: API health check
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def _api_health() -> dict:
    """Call GET /health and return the response dict. Cached 30 seconds."""
    try:
        resp = httpx.get(f"{API_BASE}/health", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
        return {"status": "error", "service": "loan-approval-api"}
    except Exception:
        return {"status": "unreachable", "service": "loan-approval-api"}


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------
st.title("🏦 Agentic AI Loan Approval System")
st.caption("Multi-agent pipeline powered by LangGraph · FastMCP · Claude Sonnet · ChromaDB")
st.divider()

# ── System Status ────────────────────────────────────────────────────────────
st.subheader("System Status")
health = _api_health()
api_status = health.get("status", "unknown")

col_s1, col_s2, col_s3 = st.columns(3)

with col_s1:
    color = "green" if api_status == "ok" else ("orange" if api_status == "degraded" else "red")
    st.metric(
        label="FastAPI Gateway",
        value="Online" if api_status in ("ok", "degraded") else "Offline",
        help=f"Status: {api_status} — {API_BASE}",
    )

with col_s2:
    rag_ok = api_status == "ok"
    st.metric(
        label="ChromaDB (RAG)",
        value="Ready" if rag_ok else "Not Ready",
        help="ChromaDB collection populated. Run `python -m rag.ingest` if not ready.",
    )

with col_s3:
    graph_ok = api_status in ("ok", "degraded")
    st.metric(
        label="LangGraph Pipeline",
        value="Compiled" if graph_ok else "Unavailable",
        help="LangGraph StateGraph pre-compiled at API startup.",
    )

if api_status == "unreachable":
    st.error(
        "FastAPI gateway is not reachable. "
        f"Start it with: `uvicorn api.main:app --port {settings.api_port} --reload`",
        icon="🔴",
    )
elif api_status == "degraded":
    st.warning(
        "API is running but ChromaDB collection is not populated. "
        "Policy lookups will return empty context. "
        "Run `python -m rag.ingest` to fix this.",
        icon="🟠",
    )
elif api_status == "ok":
    st.success("All systems operational. Ready to process loan applications.", icon="🟢")

st.divider()

# ── Navigation guide ─────────────────────────────────────────────────────────
st.subheader("Navigation")

nav_col1, nav_col2, nav_col3 = st.columns(3)

with nav_col1:
    st.info(
        "**📋 Loan Application**\n\n"
        "Submit a loan application. The AI pipeline analyses it and returns "
        "APPROVED, REJECTED, or REVIEW REQUIRED with a confidence score and "
        "full explanation.",
        icon="📋",
    )

with nav_col2:
    st.info(
        "**📊 Dashboard**\n\n"
        "Observability view of all processed applications. Shows approval rates, "
        "confidence score distribution, risk metrics, and the full audit log "
        "read directly from `audit/logs/`.",
        icon="📊",
    )

with nav_col3:
    st.info(
        "**🔀 Workflow**\n\n"
        "Visualise the LangGraph agent pipeline. Shows the static graph topology "
        "and the per-node execution trace for the last submitted application.",
        icon="🔀",
    )

st.divider()

# ── Architecture overview ─────────────────────────────────────────────────────
st.subheader("Architecture")

st.markdown("""
```
Streamlit UI (8501)
    │
    └─► FastAPI Gateway (8000)  POST /api/v1/analyze
            │
            └─► LangGraph Orchestrator
                    │
                    ├─► validate_input_node        (pure Python eligibility check)
                    ├─► applicant_profile_node  ──► validate_profile  MCP tool
                    │       │ (conditional gate)
                    │       ├─(valid)──────────────► financial_risk_node
                    │       │                              └─► calculate_risk MCP tool
                    │       │                        policy_knowledge_node
                    │       │                              └─► query_policy  MCP tool ──► ChromaDB
                    │       │                        loan_decision_node
                    │       │                              └─► generate_decision MCP tool
                    │       └─(invalid)───────────► early_rejection_node
                    │
                    └─► compliance_node  ──► create_audit MCP tool ──► audit/logs/
```
""")

# ── Session summary (if any applications submitted) ──────────────────────────
if st.session_state.application_history:
    st.divider()
    st.subheader(f"Session Summary — {len(st.session_state.application_history)} application(s) submitted")
    last = st.session_state.application_history[-1]
    verdict = last.get("verdict", "—")
    verdict_color = {"APPROVED": "green", "REJECTED": "red", "REVIEW_REQUIRED": "orange"}.get(verdict, "grey")
    st.markdown(
        f"Last verdict: **:{verdict_color}[{verdict}]** · "
        f"Case ID: `{last.get('case_id', '—')}` · "
        f"Confidence: `{last.get('confidence_score', 0):.0%}`"
    )
