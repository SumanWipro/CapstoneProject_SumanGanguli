"""
ui/pages/01_chatbot.py
=======================
Streamlit page: Loan Application Chatbot.

Responsibilities:
- Collect all 10 loan application fields via a structured form
- Validate inputs client-side (age range, income floor, loan limits)
- POST the application to FastAPI /api/v1/analyze via httpx
- Display verdict with colour-coded banner, confidence progress bar,
  plain-English explanation, and audit Case ID
- Persist result to st.session_state for Dashboard and Workflow pages

Design decision — form over pure chat:
    All 10 fields are required simultaneously by the LangGraph pipeline.
    A single st.form() collects them in one submit, preventing partial
    state. The form is laid out in two columns to feel conversational
    without being a raw JSON editor.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import streamlit as st

from config.settings import get_settings

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Loan Application",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings  = get_settings()
API_URL   = f"{settings.fastapi_base_url}/api/{settings.api_version}/analyze"

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
for key, default in [
    ("last_decision", None),
    ("last_request", None),
    ("application_history", []),
    ("pipeline_trace", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _verdict_config(verdict: str) -> tuple[str, str, str]:
    """Return (emoji, colour, banner_text) for a verdict string."""
    return {
        "APPROVED":        ("✅", "green",  "Loan Application APPROVED"),
        "REJECTED":        ("❌", "red",    "Loan Application REJECTED"),
        "REVIEW_REQUIRED": ("⚠️", "orange", "Manual Review Required"),
    }.get(verdict, ("❓", "grey", "Unknown Verdict"))


def _call_api(payload: dict) -> dict:
    """
    POST payload to FastAPI /api/v1/analyze and return the response dict.

    Raises:
        httpx.HTTPStatusError: On 4xx/5xx responses.
        httpx.RequestError:    On network errors.
    """
    resp = httpx.post(API_URL, json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("📋 Loan Application")
st.caption("Fill in the form below. The AI pipeline will analyse your application and return a decision.")
st.divider()

# ---------------------------------------------------------------------------
# Application form
# ---------------------------------------------------------------------------
with st.form("loan_application_form", clear_on_submit=False):
    st.subheader("Applicant Details")

    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        applicant_id = st.text_input(
            "Applicant ID",
            value=f"APP-{uuid.uuid4().hex[:6].upper()}",
            help="Unique identifier for this applicant. Auto-generated but editable.",
            max_chars=50,
        )
        age = st.number_input(
            "Age (years)",
            min_value=18, max_value=70, value=35, step=1,
            help="Must be between 18 and 70 inclusive.",
        )
        income = st.number_input(
            "Annual Income (INR)",
            min_value=150_000.0, max_value=50_000_000.0,
            value=800_000.0, step=10_000.0, format="%.0f",
            help="Annual gross income in Indian Rupees.",
        )
        employment_type = st.selectbox(
            "Employment Type",
            options=["salaried", "government", "self_employed", "contract",
                     "unemployed", "student"],
            index=0,
            help="salaried/government = stable; self_employed/contract = moderate; "
                 "unemployed/student = unstable.",
        )
        credit_score = st.slider(
            "CIBIL Credit Score",
            min_value=300, max_value=900, value=720, step=1,
            help="300–549: Poor | 550–649: Fair | 650–749: Good | 750–900: Excellent",
        )

    with col_right:
        loan_amount = st.number_input(
            "Loan Amount (INR)",
            min_value=10_000.0, max_value=10_000_000.0,
            value=500_000.0, step=10_000.0, format="%.0f",
            help="Requested loan principal. Maximum 3× annual income for unsecured loans.",
        )
        loan_tenure = st.number_input(
            "Loan Tenure (months)",
            min_value=6, max_value=360, value=36, step=6,
            help="Repayment period. 6–360 months.",
        )
        existing_liabilities = st.number_input(
            "Existing Monthly Liabilities (INR)",
            min_value=0.0, max_value=5_000_000.0,
            value=15_000.0, step=1_000.0, format="%.0f",
            help="Total existing EMIs, credit card minimums, and other monthly obligations.",
        )
        location = st.text_input(
            "Location (City / Region)",
            value="Mumbai",
            help="Applicant's city or region.",
            max_chars=100,
        )

    st.divider()

    # Credit score indicator
    cs_band = (
        "Excellent (750–900)" if credit_score >= 750 else
        "Good (650–749)"      if credit_score >= 650 else
        "Fair (550–649)"      if credit_score >= 550 else
        "Poor (300–549)"
    )
    dti_preview = existing_liabilities / (income / 12) if income > 0 else 0
    col_i1, col_i2, col_i3 = st.columns(3)
    col_i1.metric("Credit Band Preview", cs_band)
    col_i2.metric("DTI Preview", f"{dti_preview:.2%}",
                  help="Debt-to-Income = monthly liabilities / (income/12)")
    col_i3.metric("Loan-to-Income Ratio", f"{loan_amount/income:.1f}×",
                  help="Maximum 3× annual income for unsecured personal loans")

    st.divider()
    submitted = st.form_submit_button(
        "🚀 Submit Application",
        use_container_width=True,
        type="primary",
    )


# ---------------------------------------------------------------------------
# Handle form submission
# ---------------------------------------------------------------------------
if submitted:
    # Client-side validation
    errors = []
    if loan_amount > income * 3:
        errors.append(f"Loan amount ({loan_amount:,.0f}) exceeds 3× annual income ({income*3:,.0f}).")
    if dti_preview > 0.80:
        errors.append(f"DTI of {dti_preview:.2%} is very high. The application will likely be rejected.")

    if errors:
        for e in errors:
            st.warning(e, icon="⚠️")

    # Build request payload
    payload = {
        "applicant_id":         applicant_id,
        "age":                  int(age),
        "income":               float(income),
        "employment_type":      employment_type,
        "credit_score":         int(credit_score),
        "loan_amount":          float(loan_amount),
        "loan_tenure":          int(loan_tenure),
        "existing_liabilities": float(existing_liabilities),
        "location":             location,
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    }

    with st.spinner("Analysing application through the AI pipeline..."):
        try:
            result = _call_api(payload)

            # Persist to session state
            st.session_state.last_decision = result
            st.session_state.last_request  = payload
            st.session_state.pipeline_trace = result.get("traces", [])
            st.session_state.application_history.append(result)

        except httpx.HTTPStatusError as exc:
            st.error(
                f"API returned {exc.response.status_code}: "
                f"{exc.response.json().get('message', exc.response.text)}",
                icon="🔴",
            )
            result = None
        except httpx.RequestError:
            st.error(
                f"Could not reach the FastAPI gateway at {API_URL}. "
                f"Start it with: `uvicorn api.main:app --port {settings.api_port} --reload`",
                icon="🔴",
            )
            result = None


# ---------------------------------------------------------------------------
# Result display
# ---------------------------------------------------------------------------
if st.session_state.last_decision:
    result   = st.session_state.last_decision
    verdict  = result.get("verdict", "UNKNOWN")
    emoji, colour, banner = _verdict_config(verdict)

    st.divider()
    st.subheader("Decision Result")

    # Verdict banner
    if verdict == "APPROVED":
        st.success(f"{emoji} {banner}", icon="✅")
    elif verdict == "REJECTED":
        st.error(f"{emoji} {banner}", icon="❌")
    else:
        st.warning(f"{emoji} {banner}", icon="⚠️")

    # KPI row
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Verdict",          verdict)
    kpi2.metric("Confidence",       f"{result.get('confidence_score', 0):.0%}")
    kpi3.metric("Case ID",          result.get("case_id", "—"))
    kpi4.metric("Risk Score",       f"{result.get('risk_score', '—')}" if result.get('risk_score') else "—")

    # Second row — financial metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Credit Band",  result.get("credit_band", "—").title() if result.get("credit_band") else "—")
    m2.metric("DTI Ratio",    f"{result.get('dti', 0):.2%}" if result.get("dti") is not None else "—")
    m3.metric("Applicant ID", result.get("applicant_id", "—"))

    # Confidence progress bar
    st.markdown("**Confidence Score**")
    conf = result.get("confidence_score", 0.0)
    bar_colour = "green" if conf >= 0.80 else ("orange" if conf >= 0.50 else "red")
    st.progress(conf, text=f"{conf:.0%}")

    # Explanation
    with st.expander("Decision Explanation", expanded=True):
        st.markdown(result.get("explanation", "No explanation available."))

    # Notification summary
    if result.get("notification_summary"):
        with st.expander("Applicant Notification"):
            st.info(result["notification_summary"])

    # Raw response (for debugging)
    with st.expander("Raw API Response (JSON)", expanded=False):
        st.json(result)

    # Navigation hints
    st.divider()
    st.caption(
        "View decision history on the **Dashboard** page. "
        "See the agent execution trace on the **Workflow** page."
    )
