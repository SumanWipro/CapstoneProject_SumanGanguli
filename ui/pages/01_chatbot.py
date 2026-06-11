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

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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

# Chat state initialization (new conversational flow)
for key, default in [
    ("chat_mode", "form"),                 # "form" (legacy) or "chat" (new conversational)
    ("chat_stage", "start"),               # Chat state machine: start -> collect -> confirm -> result
    ("chat_messages", []),                 # List of {role: "user"|"assistant", content: str}
    ("chat_field_index", 0),               # Current field being collected (0-9)
    ("chat_collected_payload", {}),        # Normalized collected data
    ("chat_confirmation_pending", False),  # True if awaiting yes/no confirmation
    ("chat_field_being_edited", None),     # Field name if user is correcting a field
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

# Chat conversation configuration
CHAT_FIELDS = [
    "applicant_id", "age", "income", "employment_type", "credit_score",
    "loan_amount", "loan_tenure", "existing_liabilities", "location"
]

CHAT_PROMPTS = {
    "start": (
        "👋 Welcome to the Loan Application Chatbot!\n\n"
        "I'll collect your information step by step. "
        "You can type **summary** to see collected values, "
        "**edit <field>** to correct something, or **start over** to begin again.\n\n"
        "Let's begin! 🚀"
    ),
    "applicant_id": "What is your applicant ID? (e.g., APP-001 or auto-generate)",
    "age": "How old are you? (18–70 years)",
    "income": "What is your annual income in INR? (min 150,000)",
    "employment_type": "What is your employment type? (salaried, government, self_employed, contract, unemployed, student)",
    "credit_score": "What is your CIBIL credit score? (300–900)",
    "loan_amount": "How much loan do you need in INR? (10,000–10 million)",
    "loan_tenure": "How many months for repayment? (6–360)",
    "existing_liabilities": "What are your existing monthly liabilities in INR? (e.g., 15000)",
    "location": "What is your location/city?"
}


def _chat_add_assistant_message(content: str) -> None:
    """Append an assistant message to chat_messages."""
    st.session_state.chat_messages.append({
        "role": "assistant",
        "content": content
    })


def _chat_add_user_message(content: str) -> None:
    """Append a user message to chat_messages."""
    st.session_state.chat_messages.append({
        "role": "user",
        "content": content
    })


def _process_chat_command(command_text: str) -> tuple[bool, str]:
    """
    Process special chat commands: summary, edit <field>, start over.
    Returns (is_command, response_message).
    """
    command_lower = command_text.lower().strip()
    
    if command_lower == "summary":
        # Show all collected values
        if not st.session_state.chat_collected_payload:
            return (True, "No fields collected yet. Let's get started!")
        
        summary_lines = ["Current collected information:"]
        for field in CHAT_FIELDS:
            if field in st.session_state.chat_collected_payload:
                value = st.session_state.chat_collected_payload[field]
                summary_lines.append(f"- **{field}**: {value}")
            else:
                summary_lines.append(f"- **{field}**: (not collected yet)")
        return (True, "\n".join(summary_lines))
    
    elif command_lower.startswith("edit "):
        # Edit a specific field
        field_to_edit = command_lower[5:].strip()
        if field_to_edit not in CHAT_FIELDS:
            return (True, f"Unknown field: {field_to_edit}. Available fields: {', '.join(CHAT_FIELDS)}")
        
        field_idx = CHAT_FIELDS.index(field_to_edit)
        st.session_state.chat_field_index = field_idx
        st.session_state.chat_field_being_edited = field_to_edit
        next_prompt = CHAT_PROMPTS.get(field_to_edit, f"Please provide {field_to_edit}:")
        return (True, f"Going back to edit **{field_to_edit}**. {next_prompt}")
    
    elif command_lower == "start over":
        # Reset all chat state
        st.session_state.chat_messages = []
        st.session_state.chat_stage = "start"
        st.session_state.chat_field_index = 0
        st.session_state.chat_collected_payload = {}
        st.session_state.chat_field_being_edited = None
        return (True, "Chat reset. Starting fresh!")
    
    return (False, "")


def _parse_and_validate_field(field_name: str, user_input: str) -> tuple[bool, any, str]:
    """
    Validate and parse user input for a specific field.
    Returns (is_valid, parsed_value, error_message).
    """
    user_input = user_input.strip()
    
    try:
        if field_name == "applicant_id":
            if not user_input:
                return (False, None, "Applicant ID cannot be empty.")
            if len(user_input) > 50:
                return (False, None, "Applicant ID must be <=50 characters.")
            return (True, user_input, "")
        
        elif field_name == "age":
            age = int(user_input)
            if age < 18 or age > 70:
                return (False, None, "Age must be between 18 and 70.")
            return (True, age, "")
        
        elif field_name == "income":
            income = float(user_input)
            if income < 150_000:
                return (False, None, "Annual income must be at least 150,000 INR.")
            if income > 50_000_000:
                return (False, None, "Annual income cannot exceed 50 million INR.")
            return (True, income, "")
        
        elif field_name == "employment_type":
            valid_types = ["salaried", "government", "self_employed", "contract", "unemployed", "student"]
            if user_input.lower() not in valid_types:
                return (False, None, f"Must be one of: {', '.join(valid_types)}")
            return (True, user_input.lower(), "")
        
        elif field_name == "credit_score":
            score = int(user_input)
            if score < 300 or score > 900:
                return (False, None, "Credit score must be between 300 and 900.")
            return (True, score, "")
        
        elif field_name == "loan_amount":
            amount = float(user_input)
            if amount < 10_000:
                return (False, None, "Loan amount must be at least 10,000 INR.")
            if amount > 10_000_000:
                return (False, None, "Loan amount cannot exceed 10 million INR.")
            return (True, amount, "")
        
        elif field_name == "loan_tenure":
            tenure = int(user_input)
            if tenure < 6 or tenure > 360:
                return (False, None, "Loan tenure must be between 6 and 360 months.")
            return (True, tenure, "")
        
        elif field_name == "existing_liabilities":
            liab = float(user_input)
            if liab < 0 or liab > 5_000_000:
                return (False, None, "Existing liabilities must be between 0 and 5 million INR.")
            return (True, liab, "")
        
        elif field_name == "location":
            if not user_input:
                return (False, None, "Location cannot be empty.")
            if len(user_input) > 100:
                return (False, None, "Location must be <=100 characters.")
            return (True, user_input, "")
        
        else:
            return (False, None, "Unknown field.")
    
    except ValueError:
        return (False, None, f"Invalid input format for {field_name}. Please check and try again.")
    except Exception as e:
        return (False, None, f"Error parsing {field_name}: {str(e)}")


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
# Page header with mode toggle
# ---------------------------------------------------------------------------
st.title("📋 Loan Application")

col_title, col_mode = st.columns([3, 1])
with col_title:
    st.caption("Fill in the form or use the chatbot below. The AI pipeline will analyse your application and return a decision.")
with col_mode:
    mode_options = ["💬 Chat Mode", "📋 Form Mode"]
    current_mode_idx = 0 if st.session_state.chat_mode == "chat" else 1
    mode_selection = st.radio("Mode", mode_options, index=current_mode_idx, horizontal=True, label_visibility="collapsed")
    new_chat_mode = "chat" if mode_selection == "💬 Chat Mode" else "form"
    if new_chat_mode != st.session_state.chat_mode:
        st.session_state.chat_mode = new_chat_mode
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Conversational intake flow (Step 2+ / Form Mode Conditional)
# ---------------------------------------------------------------------------
if st.session_state.chat_mode == "chat" and st.session_state.chat_stage not in ["result"]:
    # Initialize chat on first load
    if st.session_state.chat_stage == "start" and not st.session_state.chat_messages:
        _chat_add_assistant_message(CHAT_PROMPTS["start"])
        st.session_state.chat_stage = "collect"
    
    # Display chat history (read-only)
    st.subheader("💬 Chat Intake")
    chat_container = st.container(height=300, border=True)
    
    with chat_container:
        for msg in st.session_state.chat_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(msg["content"])
    
    # Get current field
    current_field_index = st.session_state.chat_field_index
    if current_field_index < len(CHAT_FIELDS):
        current_field = CHAT_FIELDS[current_field_index]
        current_prompt = CHAT_PROMPTS.get(current_field, f"Please provide {current_field}:")
        
        # Input section with columns
        st.divider()
        col_input, col_submit = st.columns([4, 1])
        
        with col_input:
            user_answer = st.text_input(
                f"Your response ({current_field_index + 1}/{len(CHAT_FIELDS)})",
                placeholder=current_prompt,
                key=f"chat_input_{current_field_index}",
                label_visibility="collapsed"
            )
        
        with col_submit:
            submit_answer = st.button("Send", key=f"chat_send_{current_field_index}", use_container_width=True)
        
        # Process answer
        if submit_answer and user_answer:
            # Check for commands first
            is_command, command_response = _process_chat_command(user_answer)
            
            if is_command:
                # It's a command, display response
                _chat_add_user_message(user_answer)
                _chat_add_assistant_message(command_response)
                
                if user_answer.lower().strip().startswith("edit "):
                    # After edit command, re-ask the field
                    field_to_edit = user_answer.lower().strip()[5:].strip()
                    if field_to_edit in CHAT_FIELDS:
                        field_idx = CHAT_FIELDS.index(field_to_edit)
                        next_prompt = CHAT_PROMPTS.get(field_to_edit, f"Please provide {field_to_edit}:")
                        _chat_add_assistant_message(next_prompt)
                elif user_answer.lower().strip() == "start over":
                    # Re-initialize with welcome message
                    _chat_add_assistant_message(CHAT_PROMPTS["start"])
                
                st.rerun()
            else:
                # Normal field validation
                is_valid, parsed_value, error_msg = _parse_and_validate_field(current_field, user_answer)
                
                if is_valid:
                    # Add user message
                    _chat_add_user_message(user_answer)
                    
                    # Store in collected payload
                    st.session_state.chat_collected_payload[current_field] = parsed_value
                    
                    # Clear field being edited flag
                    st.session_state.chat_field_being_edited = None
                    
                    # Move to next field
                    st.session_state.chat_field_index += 1
                    
                    if st.session_state.chat_field_index < len(CHAT_FIELDS):
                        # Add assistant question for next field
                        next_field = CHAT_FIELDS[st.session_state.chat_field_index]
                        next_prompt = CHAT_PROMPTS.get(next_field, f"Please provide {next_field}:")
                        _chat_add_assistant_message(next_prompt)
                    else:
                        # All fields collected, show confirmation
                        _chat_add_assistant_message(
                            "All information collected! Please review and confirm your details below before submitting."
                        )
                        st.session_state.chat_stage = "confirm"

                    st.rerun()
                else:
                    # Validation failed
                    st.error(f"Error: {error_msg}", icon="")
    
    st.divider()

# ---------------------------------------------------------------------------
# Confirmation stage (Step 4+)
# ---------------------------------------------------------------------------
if st.session_state.chat_stage == "confirm":
    # Display chat history (read-only)
    st.subheader("💬 Chat Intake")
    chat_container = st.container(height=250, border=True)
    
    with chat_container:
        for msg in st.session_state.chat_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(msg["content"])
    
    # Display summary of collected values
    st.divider()
    st.subheader("📋 Review Your Information")
    
    col1, col2 = st.columns(2)
    with col1:
        for i, field in enumerate(CHAT_FIELDS[:5]):
            value = st.session_state.chat_collected_payload.get(field, "—")
            st.metric(field.replace("_", " ").title(), str(value))
    
    with col2:
        for field in CHAT_FIELDS[5:]:
            value = st.session_state.chat_collected_payload.get(field, "—")
            st.metric(field.replace("_", " ").title(), str(value))
    
    # Confirmation buttons
    st.divider()
    col_yes, col_no, col_edit = st.columns(3)
    
    with col_yes:
        confirm_yes = st.button("✅ Confirm & Submit", use_container_width=True, type="primary", key="chat_confirm_yes")
    
    with col_no:
        confirm_no = st.button("❌ Not Ready", use_container_width=True, key="chat_confirm_no")
    
    with col_edit:
        confirm_edit = st.button("✏️ Edit", use_container_width=True, key="chat_confirm_edit")
    
    # Handle confirmation responses
    if confirm_yes:
        # Build final payload from chat_collected_payload + timestamp
        final_payload = dict(st.session_state.chat_collected_payload)
        final_payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Submit to API
        with st.spinner("Submitting application..."):
            try:
                result = _call_api(final_payload)
                
                # Persist to session state
                st.session_state.last_decision = result
                st.session_state.last_request = final_payload
                st.session_state.pipeline_trace = result.get("traces", [])
                st.session_state.application_history.append(result)
                
                # Add confirmation message to chat
                _chat_add_assistant_message("✅ Application submitted successfully! Your decision is ready below.")
                st.session_state.chat_stage = "result"
                
                st.rerun()
            
            except httpx.HTTPStatusError as exc:
                error_detail = exc.response.json().get('message', exc.response.text)
                st.error(f"API Error {exc.response.status_code}: {error_detail}", icon="🔴")
            except httpx.RequestError:
                st.error(
                    f"Could not reach the FastAPI gateway at {API_URL}. "
                    f"Start it with: `uvicorn api.main:app --port {settings.api_port} --reload`",
                    icon="🔴",
                )
    
    elif confirm_no:
        # User not ready, allow editing
        _chat_add_user_message("I need to review this more carefully.")
        _chat_add_assistant_message(
            "No problem! You can use **edit <field>** to change any information. "
            "For example: `edit income` or `edit loan_amount`. What would you like to adjust?"
        )
        st.session_state.chat_stage = "collect"
        st.rerun()
    
    elif confirm_edit:
        # Provide edit guidance
        _chat_add_user_message("I want to edit some information.")
        fields_str = ", ".join(CHAT_FIELDS)
        _chat_add_assistant_message(
            f"Sure! Type **edit <field>** to modify a value. Available fields: {fields_str}"
        )
        st.session_state.chat_stage = "collect"
        st.rerun()

# ---------------------------------------------------------------------------
# Result stage - conversational decision display (Step 5+)
# ---------------------------------------------------------------------------
if st.session_state.chat_stage == "result" and st.session_state.last_decision:
    result = st.session_state.last_decision
    verdict = result.get("verdict", "UNKNOWN")
    emoji, colour, banner = _verdict_config(verdict)
    
    # Display chat history
    st.subheader("💬 Chat Intake")
    chat_container = st.container(height=250, border=True)
    
    with chat_container:
        for msg in st.session_state.chat_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(msg["content"])
    
    # Verdict announcement in conversational format
    st.divider()
    st.subheader("📊 Decision Result")
    
    # Verdict banner
    if verdict == "APPROVED":
        st.success(f"{emoji} {banner}", icon="✅")
        friendly_msg = "🎉 Great news! Your loan application has been **APPROVED**!"
    elif verdict == "REJECTED":
        st.error(f"{emoji} {banner}", icon="❌")
        friendly_msg = "Unfortunately, your application has been **REJECTED** at this time."
    else:
        st.warning(f"{emoji} {banner}", icon="⚠️")
        friendly_msg = "Your application requires **MANUAL REVIEW** by our team."
    
    st.markdown(f"**{friendly_msg}**")
    st.write("")
    
    # Key metrics row
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Verdict", verdict)
    kpi2.metric("Confidence", f"{result.get('confidence_score', 0):.0%}")
    kpi3.metric("Case ID", result.get("case_id", "—")[:12])
    kpi4.metric("Risk Score", f"{result.get('risk_score', '—')}" if result.get('risk_score') else "—")
    
    # Financial metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Credit Band", result.get("credit_band", "—").title() if result.get("credit_band") else "—")
    m2.metric("DTI Ratio", f"{result.get('dti', 0):.2%}" if result.get("dti") is not None else "—")
    m3.metric("Loan-to-Income", f"{(result.get('loan_amount', 0) / result.get('income', 1)):.1f}×" if result.get('income') else "—")
    
    # Confidence visualization
    st.markdown("**Decision Confidence**")
    conf = result.get("confidence_score", 0.0)
    st.progress(conf, text=f"{conf:.0%}")
    
    # Decision explanation
    explanation = result.get("explanation", "No detailed explanation available.")
    with st.expander("Decision Explanation", expanded=True):
        st.markdown(explanation)
    
    # Notification for applicant
    if result.get("notification_summary"):
        with st.expander("Important Information", expanded=False):
            st.info(result["notification_summary"])

    if verdict == "REVIEW_REQUIRED":
        with st.expander("Manual Review Workflow", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Review Queue:** {result.get('review_queue', '—')}")
                st.markdown(f"**Reviewer Role:** {result.get('reviewer_role', '—')}")
                st.markdown(f"**Review Owner:** {result.get('manual_review_owner', '—')}")
            with c2:
                st.markdown(f"**Review Status:** {result.get('review_status', '—')}")
                st.markdown(f"**Due Timestamp:** {result.get('review_due_timestamp', '—')}")
                st.markdown(f"**Last Transition:** {result.get('status_transition', '—')}")
    
    # Action buttons
    st.divider()
    col_new, col_details, col_history = st.columns(3)
    
    with col_new:
        if st.button("📝 New Application", use_container_width=True):
            # Reset chat state for new application
            st.session_state.chat_mode = "form"
            st.session_state.chat_stage = "start"
            st.session_state.chat_messages = []
            st.session_state.chat_field_index = 0
            st.session_state.chat_collected_payload = {}
            st.session_state.chat_confirmation_pending = False
            st.session_state.chat_field_being_edited = None
            st.rerun()
    
    with col_details:
        st.button("📋 Full Details", use_container_width=True, disabled=True, help="Scroll down to see full result")
    
    with col_history:
        if st.button("📊 View History", use_container_width=True):
            st.session_state.chat_mode = "form"
            st.switch_page("pages/02_dashboard.py")
    
    st.divider()

# ---------------------------------------------------------------------------
# Application form (fallback or primary mode)
# ---------------------------------------------------------------------------
if st.session_state.chat_mode == "form" or st.session_state.chat_stage in ["result"]:
    # Populate form with chat-collected values or defaults
    default_applicant_id = st.session_state.chat_collected_payload.get("applicant_id", f"APP-{uuid.uuid4().hex[:6].upper()}")
    default_age = st.session_state.chat_collected_payload.get("age", 35)
    default_income = st.session_state.chat_collected_payload.get("income", 800_000.0)
    default_employment = st.session_state.chat_collected_payload.get("employment_type", "salaried")
    default_credit = st.session_state.chat_collected_payload.get("credit_score", 720)
    default_loan_amount = st.session_state.chat_collected_payload.get("loan_amount", 500_000.0)
    default_tenure = st.session_state.chat_collected_payload.get("loan_tenure", 36)
    default_liabilities = st.session_state.chat_collected_payload.get("existing_liabilities", 15_000.0)
    default_location = st.session_state.chat_collected_payload.get("location", "Mumbai")
    
    # Use expander for result stage reference, container for form mode
    if st.session_state.chat_stage == "result":
        form_container = st.expander("📋 Form (Reference)", expanded=False)
    else:
        form_container = st.container()
    
    with form_container:
        with st.form("loan_application_form", clear_on_submit=False):
            st.subheader("Applicant Details")

            col_left, col_right = st.columns(2, gap="large")

            with col_left:
                applicant_id = st.text_input(
                    "Applicant ID",
                    value=str(default_applicant_id),
                    help="Unique identifier for this applicant. Auto-generated but editable.",
                    max_chars=50,
                )
                age = st.number_input(
                    "Age (years)",
                    min_value=18, max_value=70, value=int(default_age), step=1,
                    help="Must be between 18 and 70 inclusive.",
                )
                income = st.number_input(
                    "Annual Income (INR)",
                    min_value=150_000.0, max_value=50_000_000.0,
                    value=float(default_income), step=10_000.0, format="%.0f",
                    help="Annual gross income in Indian Rupees.",
                )
                employment_type = st.selectbox(
                    "Employment Type",
                    options=["salaried", "government", "self_employed", "contract",
                             "unemployed", "student"],
                    index=["salaried", "government", "self_employed", "contract", "unemployed", "student"].index(str(default_employment)),
                    help="salaried/government = stable; self_employed/contract = moderate; "
                         "unemployed/student = unstable.",
                )
                credit_score = st.slider(
                    "CIBIL Credit Score",
                    min_value=300, max_value=900, value=int(default_credit), step=1,
                    help="300–549: Poor | 550–649: Fair | 650–749: Good | 750–900: Excellent",
                )

            with col_right:
                loan_amount = st.number_input(
                    "Loan Amount (INR)",
                    min_value=10_000.0, max_value=10_000_000.0,
                    value=float(default_loan_amount), step=10_000.0, format="%.0f",
                    help="Requested loan principal. Maximum 3× annual income for unsecured loans.",
                )
                loan_tenure = st.number_input(
                    "Loan Tenure (months)",
                    min_value=6, max_value=360, value=int(default_tenure), step=6,
                    help="Repayment period. 6–360 months.",
                )
                existing_liabilities = st.number_input(
                    "Existing Monthly Liabilities (INR)",
                    min_value=0.0, max_value=5_000_000.0,
                    value=float(default_liabilities), step=1_000.0, format="%.0f",
                    help="Total existing EMIs, credit card minimums, and other monthly obligations.",
                )
                location = st.text_input(
                    "Location (City / Region)",
                    value=str(default_location),
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
# Result display (fallback for form mode)
# ---------------------------------------------------------------------------
if st.session_state.last_decision and st.session_state.chat_stage != "result":
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
