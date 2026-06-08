"""
ui/pages/03_workflow.py
========================
Streamlit page: LangGraph Workflow Visualisation.

Responsibilities:
- Render the static LangGraph pipeline topology as a Mermaid diagram
- Display which nodes executed for the last submitted application
- Show per-node agent output from st.session_state.last_decision
- Provide an agent responsibility reference table

Design decision — session state as trace source:
    The LangGraph MemorySaver checkpointer stores state snapshots, but
    accessing them requires the compiled graph object (not available in
    the UI process). Instead, the pipeline result stored in
    st.session_state.last_decision contains all agent outputs (profile,
    risk, policy, decision, audit) which are displayed per-node here.
"""

from __future__ import annotations

import json

import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Workflow",
    page_icon="🔀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state guard
# ---------------------------------------------------------------------------
for key, default in [
    ("last_decision", None),
    ("last_request", None),
    ("pipeline_trace", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("🔀 LangGraph Workflow Visualisation")
st.caption("Pipeline topology and per-node execution trace for the last submitted application.")
st.divider()

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------
tab_topology, tab_trace, tab_agents = st.tabs([
    "Pipeline Topology",
    "Execution Trace",
    "Agent Reference",
])


# ===========================================================================
# Tab 1: Pipeline Topology
# ===========================================================================
with tab_topology:
    st.subheader("LangGraph StateGraph — Full Pipeline Topology")
    st.caption(
        "The graph has a conditional gate after the Profile node. "
        "Invalid profiles are rejected immediately without invoking "
        "the Risk, Policy, or Decision agents."
    )

    # Full pipeline Mermaid diagram
    st.markdown("""
```mermaid
flowchart TD
    START([START]) --> V[validate_input_node\n─────────────────\nField presence check\nAge range 18-70\nCredit score 300-900]

    V --> P[applicant_profile_node\n─────────────────\nMCP: validate_profile\nAgent 1: ProfileAgent\nEmployment band mapping]

    P --> GATE{_profile_gate\n───────────\nearly_exit?\nprofile valid?}

    GATE -- Valid --> FR[financial_risk_node\n─────────────────\nMCP: calculate_risk\nAgent 2: RiskAgent\nDTI · Credit band · Risk score]

    GATE -- Invalid --> ER[early_rejection_node\n─────────────────\nNo LLM call\nRejected immediately\nConf = 0.95]

    FR --> PK[policy_knowledge_node\n─────────────────\nMCP: query_policy\nAgent 3: PolicyAgent\nRAG via ChromaDB]

    PK --> LD[loan_decision_node\n─────────────────\nMCP: generate_decision\nAgent 4: DecisionAgent\nAPPROVED / REJECTED / REVIEW]

    LD --> C[compliance_node\n─────────────────\nMCP: create_audit\nAgent 5: ComplianceAgent\nCase ID · Audit log]

    ER --> C

    C --> END([END])

    style START fill:#1e293b,color:#fff
    style END   fill:#1e293b,color:#fff
    style GATE  fill:#7c3aed,color:#fff
    style ER    fill:#dc2626,color:#fff
    style C     fill:#0369a1,color:#fff
```
""")

    st.divider()
    st.subheader("Conditional Routing Logic")

    col_gate1, col_gate2 = st.columns(2)
    with col_gate1:
        st.success(
            "**Route: financial_risk_node**\n\n"
            "- `early_exit == False`\n"
            "- `profile_result.valid == True`\n"
            "- All 10 fields present\n"
            "- Age in [18, 70]"
        )
    with col_gate2:
        st.error(
            "**Route: early_rejection_node**\n\n"
            "- `early_exit == True` (set by validate_input)\n"
            "- `profile_result.valid == False`\n"
            "- Age < 18 or > 70\n"
            "- Missing required fields"
        )


# ===========================================================================
# Tab 2: Execution Trace
# ===========================================================================
with tab_trace:
    st.subheader("Last Application — Execution Trace")

    result  = st.session_state.last_decision
    request = st.session_state.last_request

    if not result:
        st.info(
            "No application submitted yet. Submit one on the **Loan Application** page "
            "to see the execution trace here.",
            icon="👈",
        )
        st.stop()

    # Summary header
    verdict = result.get("verdict", "UNKNOWN")
    verdict_icon = {"APPROVED": "✅", "REJECTED": "❌", "REVIEW_REQUIRED": "⚠️"}.get(verdict, "❓")
    st.markdown(
        f"**Applicant:** `{result.get('applicant_id', '—')}` &nbsp;|&nbsp; "
        f"**Verdict:** {verdict_icon} `{verdict}` &nbsp;|&nbsp; "
        f"**Case ID:** `{result.get('case_id', '—')}` &nbsp;|&nbsp; "
        f"**Confidence:** `{result.get('confidence_score', 0):.0%}`"
    )
    st.divider()

    # Determine which path was taken
    early_exit_taken = (verdict == "REJECTED" and not result.get("risk_score"))

    # ── Node 1: validate_input ────────────────────────────────────────────
    with st.expander("Node 1 — validate_input_node", expanded=True):
        col_n1a, col_n1b = st.columns([1, 2])
        with col_n1a:
            st.markdown("**Status:** ✅ Executed")
            st.markdown("**Type:** Pure Python (no LLM)")
            st.markdown("**Result:** Input validated")
        with col_n1b:
            if request:
                st.json({
                    "applicant_id":    request.get("applicant_id"),
                    "age":             request.get("age"),
                    "credit_score":    request.get("credit_score"),
                    "income":          request.get("income"),
                    "employment_type": request.get("employment_type"),
                })

    # ── Node 2: applicant_profile_node ───────────────────────────────────
    with st.expander("Node 2 — applicant_profile_node", expanded=True):
        col_n2a, col_n2b = st.columns([1, 2])
        with col_n2a:
            st.markdown("**Status:** ✅ Executed")
            st.markdown("**MCP Tool:** `validate_profile`")
            st.markdown("**Agent:** ApplicantProfileAgent")
            credit_band = result.get("credit_band", "—")
            employment_band = "stable"  # surfaced from profile
            st.markdown(f"**Credit Band:** `{credit_band}`")
        with col_n2b:
            st.json({
                "credit_band":    result.get("credit_band", "—"),
                "dti":            result.get("dti"),
                "risk_score":     result.get("risk_score"),
            })

    # ── Conditional gate ─────────────────────────────────────────────────
    gate_col1, gate_col2 = st.columns(2)
    with gate_col1:
        if early_exit_taken:
            st.error("**_profile_gate** → early_rejection_node", icon="🔀")
        else:
            st.success("**_profile_gate** → financial_risk_node", icon="🔀")

    # ── Happy path nodes ─────────────────────────────────────────────────
    if not early_exit_taken:
        with st.expander("Node 3 — financial_risk_node", expanded=True):
            col_n3a, col_n3b = st.columns([1, 2])
            with col_n3a:
                st.markdown("**Status:** ✅ Executed")
                st.markdown("**MCP Tool:** `calculate_risk`")
                st.markdown("**Agent:** FinancialRiskAgent")
            with col_n3b:
                st.json({
                    "dti":         result.get("dti"),
                    "credit_band": result.get("credit_band"),
                    "risk_score":  result.get("risk_score"),
                })

        with st.expander("Node 4 — policy_knowledge_node", expanded=True):
            col_n4a, col_n4b = st.columns([1, 2])
            with col_n4a:
                st.markdown("**Status:** ✅ Executed")
                st.markdown("**MCP Tool:** `query_policy`")
                st.markdown("**Agent:** PolicyKnowledgeAgent (RAG)")
                st.markdown("**Source:** ChromaDB")
            with col_n4b:
                st.markdown("*Policy context retrieved and passed to Decision Agent.*")
                st.caption("Full policy chunks not surfaced in API response — see audit log.")

        with st.expander("Node 5 — loan_decision_node", expanded=True):
            col_n5a, col_n5b = st.columns([1, 2])
            with col_n5a:
                st.markdown("**Status:** ✅ Executed")
                st.markdown("**MCP Tool:** `generate_decision`")
                st.markdown("**Agent:** LoanDecisionAgent")
                st.markdown(f"**Verdict:** `{verdict}`")
                st.markdown(f"**Confidence:** `{result.get('confidence_score', 0):.0%}`")
            with col_n5b:
                st.json({
                    "verdict":     verdict,
                    "confidence":  result.get("confidence_score"),
                    "explanation": result.get("explanation", "")[:200] + "...",
                })
    else:
        with st.expander("Node 6 — early_rejection_node", expanded=True):
            col_er_a, col_er_b = st.columns([1, 2])
            with col_er_a:
                st.markdown("**Status:** ✅ Executed (early exit path)")
                st.markdown("**Type:** No LLM call")
                st.markdown("**Confidence:** 0.95 (hard rule)")
            with col_er_b:
                st.json({
                    "verdict":     "REJECTED",
                    "confidence":  0.95,
                    "explanation": result.get("explanation", ""),
                })

    # ── Review action node (always runs) ─────────────────────────────────
    with st.expander("Node 7 — review_action_node (always executes)", expanded=True):
        col_ra_a, col_ra_b = st.columns([1, 2])
        with col_ra_a:
            st.markdown("**Status:** ✅ Executed")
            st.markdown("**MCP Tool:** `orchestrate_review_action`")
            st.markdown("**Agent:** ReviewActionOrchestrator")
            st.markdown(f"**Review Status:** `{result.get('review_status', 'NOT_REQUIRED')}`")
        with col_ra_b:
            st.json({
                "action_taken": result.get("action_taken"),
                "review_queue": result.get("review_queue"),
                "manual_review_owner": result.get("manual_review_owner"),
                "reviewer_role": result.get("reviewer_role"),
                "review_due_timestamp": result.get("review_due_timestamp"),
                "status_transition": result.get("status_transition"),
            })

    # ── Compliance node (always runs) ─────────────────────────────────────
    with st.expander("Node 8 — compliance_node (always executes)", expanded=True):
        col_nc_a, col_nc_b = st.columns([1, 2])
        with col_nc_a:
            st.markdown("**Status:** ✅ Executed")
            st.markdown("**MCP Tool:** `create_audit`")
            st.markdown("**Agent:** ComplianceAgent")
            st.markdown(f"**Case ID:** `{result.get('case_id', '—')}`")
        with col_nc_b:
            st.json({
                "case_id":              result.get("case_id"),
                "notification_summary": result.get("notification_summary", ""),
            })

    st.divider()
    st.markdown("**Full API Response**")
    st.json(result)


# ===========================================================================
# Tab 3: Agent Reference
# ===========================================================================
with tab_agents:
    st.subheader("Agent Responsibility Reference")

    agents_data = [
        {
            "Agent": "1. Applicant Profile Agent",
            "MCP Tool": "validate_profile",
            "Responsibility": "Validates fields, maps employment to stability band, flags eligibility issues",
            "Returns": "valid, flags, employment_band, age_eligible, income_consistent",
            "Triggers Early Exit": "Yes — if valid=False",
        },
        {
            "Agent": "2. Financial Risk Agent",
            "MCP Tool": "calculate_risk",
            "Responsibility": "Calculates DTI, maps credit score to band, computes composite risk score 0-100",
            "Returns": "dti, credit_band, risk_score, risk_flags",
            "Triggers Early Exit": "No",
        },
        {
            "Agent": "3. Policy Knowledge Agent",
            "MCP Tool": "query_policy",
            "Responsibility": "RAG retrieval from ChromaDB, identifies applicable policy clauses",
            "Returns": "chunks, sources, applicable_clauses, policy_summary",
            "Triggers Early Exit": "No (non-fatal on error)",
        },
        {
            "Agent": "4. Loan Decision Agent",
            "MCP Tool": "generate_decision",
            "Responsibility": "Synthesises all prior outputs, classifies APPROVED/REJECTED/REVIEW_REQUIRED",
            "Returns": "verdict, confidence, explanation",
            "Triggers Early Exit": "No",
        },
        {
            "Agent": "5. Review Action Orchestrator",
            "MCP Tool": "orchestrate_review_action",
            "Responsibility": "Assigns queue, reviewer role, owner placeholder, and SLA due timestamp for manual review",
            "Returns": "action_taken, review_queue, reviewer_role, review_due_timestamp, review_status",
            "Triggers Early Exit": "No (always runs)",
        },
        {
            "Agent": "6. Compliance Agent",
            "MCP Tool": "create_audit",
            "Responsibility": "Generates Case ID, writes audit record, produces applicant notification",
            "Returns": "case_id, log_path, notification_summary",
            "Triggers Early Exit": "No (always runs)",
        },
    ]

    st.dataframe(
        agents_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Agent":               st.column_config.TextColumn("Agent", width="medium"),
            "MCP Tool":            st.column_config.TextColumn("MCP Tool", width="small"),
            "Responsibility":      st.column_config.TextColumn("Responsibility", width="large"),
            "Returns":             st.column_config.TextColumn("Returns", width="large"),
            "Triggers Early Exit": st.column_config.TextColumn("Early Exit?", width="small"),
        },
    )

    st.divider()
    st.subheader("Decision Rules")

    rule_col1, rule_col2, rule_col3 = st.columns(3)
    with rule_col1:
        st.success(
            "**APPROVED**\n\n"
            "- risk_score < 40\n"
            "- credit_band in [excellent, good]\n"
            "- DTI < 0.45\n"
            "- No hard rejection triggers"
        )
    with rule_col2:
        st.error(
            "**REJECTED**\n\n"
            "- risk_score > 70, OR\n"
            "- credit_score < 500, OR\n"
            "- DTI > 0.60, OR\n"
            "- age_eligible == False"
        )
    with rule_col3:
        st.warning(
            "**REVIEW REQUIRED**\n\n"
            "- All other cases\n"
            "- risk_score 40-70\n"
            "- Borderline thresholds\n"
            "- Human underwriter decision"
        )
