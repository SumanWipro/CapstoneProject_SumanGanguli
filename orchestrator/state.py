"""
orchestrator/state.py
=====================
Shared state schema for the LangGraph loan approval pipeline.

Responsibilities:
- Define AgentState TypedDict — the single mutable object passed between
  all graph nodes via LangGraph's state management layer
- Declare sub-TypedDicts for each agent's structured output
- Provide state helper functions used by nodes and the FastAPI route

Architecture note:
    AgentState is a TypedDict (not Pydantic BaseModel) because LangGraph
    requires TypedDict or dataclass for StateGraph. Pydantic models for
    the same data live in api/models/agents.py for MCP tool validation.
    The two coexist: TypedDict for graph internals, Pydantic for boundaries.

State lifecycle:
    1. api/routes/analyze.py     → creates initial state via request.to_agent_state()
    2. validate_input_node       → validates, sets early_exit on failure
    3. applicant_profile_node    → writes profile_result
    4. financial_risk_node       → writes risk_result
    5. policy_knowledge_node     → writes policy_chunks
    6. loan_decision_node        → writes verdict, confidence_score, explanation
    7. compliance_node           → writes case_id, audit_record
    8. api/routes/analyze.py     → reads final state, builds LoanDecisionResponse
"""

from __future__ import annotations

from typing import Literal, Optional
from typing_extensions import TypedDict


# ===========================================================================
# Agent output sub-TypedDicts
# Each maps 1:1 to the corresponding Pydantic model in api/models/agents.py
# ===========================================================================

class ProfileResult(TypedDict, total=False):
    """
    Output written by applicant_profile_node into state["profile_result"].

    Fields:
        valid:             True only if all profile checks pass. False triggers
                           routing to early_rejection_node.
        flags:             List of validation issue codes. Empty = no issues.
                           Example values: "AGE_INELIGIBLE", "INCOME_TOO_LOW",
                           "EMPLOYMENT_UNSTABLE", "INCOME_INCONSISTENT".
        employment_band:   Stability classification of employment_type.
                           "stable"   → salaried, government
                           "moderate" → self_employed, contract
                           "unstable" → unemployed, student
        age_eligible:      True if age is in the range [18, 70] inclusive.
        income_consistent: True if income is plausible for the declared
                           employment type (not implausibly low).
    """

    valid: bool
    flags: list[str]
    employment_band: str          # "stable" | "moderate" | "unstable"
    age_eligible: bool
    income_consistent: bool


class RiskResult(TypedDict, total=False):
    """
    Output written by financial_risk_node into state["risk_result"].

    Fields:
        dti:          Debt-to-income ratio calculated as:
                      existing_liabilities / (annual_income / 12)
                      Interpretation:
                        <= 0.30 → low risk
                        0.31–0.45 → medium risk
                        0.46–0.60 → high risk (REVIEW_REQUIRED)
                        > 0.60  → auto-reject
        credit_band:  CIBIL credit score band.
                      "excellent" → 750–900
                      "good"      → 650–749
                      "fair"      → 550–649
                      "poor"      → 300–549
        risk_score:   Composite risk score 0–100. Higher = more risk.
                      < 40  → APPROVED range
                      40–70 → REVIEW_REQUIRED range
                      > 70  → REJECTED range
        risk_flags:   List of active risk trigger codes. Examples:
                      "high_dti", "poor_credit", "unstable_employment",
                      "high_loan_to_income", "thin_credit_file".
    """

    dti: float
    credit_band: str              # "excellent" | "good" | "fair" | "poor"
    risk_score: float             # 0.0–100.0 composite score
    risk_flags: list[str]


class PolicyChunks(TypedDict, total=False):
    """
    Output written by policy_knowledge_node into state["policy_chunks"].

    Fields:
        chunks:             Raw retrieved policy text segments from ChromaDB,
                            ordered by relevance (most relevant first).
        sources:            Source document filenames corresponding to each
                            chunk (e.g. "credit_policy.txt").
        applicable_clauses: Claude-identified clauses directly applicable to
                            this applicant. Passed to the Decision Agent.
        policy_summary:     One-paragraph synthesis from the Policy Agent
                            describing how policies apply to this applicant.
    """

    chunks: list[str]
    sources: list[str]
    applicable_clauses: list[str]
    policy_summary: str


class DecisionResult(TypedDict, total=False):
    """
    Output written by loan_decision_node into state["decision_result"].

    Fields:
        verdict:     Final loan classification.
                     "APPROVED"         → meets all criteria
                     "REJECTED"         → fails one or more hard rules
                     "REVIEW_REQUIRED"  → borderline; needs human underwriter
        confidence:  Model confidence in the verdict, range 0.0–1.0.
                     >= 0.80 → clear decision (well within thresholds)
                     0.50–0.79 → borderline (near threshold, REVIEW_REQUIRED)
        explanation: Plain-English rationale (2–4 sentences) referencing
                     specific financial factors (DTI, credit score, income).
    """

    verdict: Literal["APPROVED", "REJECTED", "REVIEW_REQUIRED"]
    confidence: float             # 0.0–1.0
    explanation: str


class AuditRecord(TypedDict, total=False):
    """
    Output written by compliance_node into state["audit_record"].

    Fields:
        case_id:              Unique Case ID. Format: CASE-YYYYMMDD-NNNN.
                              Derived from the UTC decision date + sequence.
        log_path:             Absolute path to the audit JSONL file written.
        notification_summary: Applicant-facing notification text (3–5 sentences)
                              generated by the Compliance Agent.
    """

    case_id: str
    log_path: str
    notification_summary: str


# ===========================================================================
# Master AgentState
# ===========================================================================

class AgentState(TypedDict, total=False):
    """
    Complete shared state object flowing through every LangGraph node.

    This is the single source of truth for all data within a pipeline run.
    Every node reads from it and returns a partial dict to update it.
    LangGraph merges the returned partial dict into the full state.

    Field groups:
        1. Input      — populated once from LoanApplicationRequest.to_agent_state()
        2. Intermediate — each node writes its agent's output here
        3. Output     — final fields surfaced in LoanDecisionResponse
        4. Control    — routing flags used by conditional edges

    Invariants maintained by the graph:
        - profile_result is set before financial_risk_node executes
        - risk_result is set before policy_knowledge_node executes
        - policy_chunks is set before loan_decision_node executes
        - verdict is set before compliance_node executes
        - case_id is set before the graph reaches END
        - early_exit=True causes the graph to skip risk/policy/decision nodes
    """

    # ------------------------------------------------------------------
    # Group 1: Input fields (from LoanApplicationRequest)
    # Populated once at graph entry; never overwritten by nodes.
    # ------------------------------------------------------------------

    applicant_id: str
    """Unique applicant identifier. Echoed in every log record."""

    age: int
    """Applicant age in years. Range 18–70 for eligibility."""

    income: float
    """Annual gross income in INR. Used for DTI and loan-to-income checks."""

    employment_type: str
    """Raw employment category string from the request."""

    credit_score: int
    """CIBIL credit score, range 300–900."""

    loan_amount: float
    """Requested loan principal in INR."""

    loan_tenure: int
    """Loan repayment period in months."""

    existing_liabilities: float
    """Current monthly debt obligations in INR. Used for DTI calculation."""

    location: str
    """Applicant city or region. Used in audit records."""

    timestamp: str
    """ISO 8601 application submission timestamp."""

    # ------------------------------------------------------------------
    # Group 2: Intermediate results (written by agent nodes)
    # Each node writes exactly one field. None until that node executes.
    # ------------------------------------------------------------------

    profile_result: Optional[ProfileResult]
    """Written by applicant_profile_node. None until that node executes."""

    risk_result: Optional[RiskResult]
    """Written by financial_risk_node. None until that node executes."""

    policy_chunks: Optional[PolicyChunks]
    """Written by policy_knowledge_node. None until that node executes."""

    decision_result: Optional[DecisionResult]
    """Written by loan_decision_node. None until that node executes."""

    audit_record: Optional[AuditRecord]
    """Written by compliance_node. None until that node executes."""

    # ------------------------------------------------------------------
    # Group 3: Output fields (surfaced in LoanDecisionResponse)
    # Promoted from agent results by their respective nodes.
    # ------------------------------------------------------------------

    verdict: Optional[Literal["APPROVED", "REJECTED", "REVIEW_REQUIRED"]]
    """Final classification. Promoted from decision_result by loan_decision_node."""

    confidence_score: Optional[float]
    """Confidence 0.0–1.0. Promoted from decision_result by loan_decision_node."""

    explanation: Optional[str]
    """Decision rationale. Promoted from decision_result by loan_decision_node."""

    case_id: Optional[str]
    """Audit Case ID. Promoted from audit_record by compliance_node."""

    # ------------------------------------------------------------------
    # Group 4: Control flags (used by conditional edges)
    # ------------------------------------------------------------------

    error: Optional[str]
    """
    Set by any node that encounters an unrecoverable error. When set,
    the graph skips remaining agent nodes and routes to compliance_node
    for error audit logging.
    """

    early_exit: bool
    """
    Set to True by validate_input_node or applicant_profile_node when
    the application fails hard eligibility checks (age, missing fields).
    Causes profile_gate to route to early_rejection_node, bypassing
    financial_risk_node, policy_knowledge_node, and loan_decision_node.
    """


# ===========================================================================
# State helper functions
# ===========================================================================

def state_to_response_dict(state: AgentState) -> dict:
    """
    Extract the final output fields from a completed AgentState for
    building a LoanDecisionResponse.

    Args:
        state: Completed AgentState after the graph has reached END.

    Returns:
        Dict with keys: applicant_id, verdict, confidence_score, explanation,
        case_id, notification_summary, risk_score, credit_band, dti.

    Usage:
        response_data = state_to_response_dict(final_state)
        response = LoanDecisionResponse(**response_data)
    """
    risk = state.get("risk_result") or {}
    audit = state.get("audit_record") or {}

    return {
        "applicant_id":         state.get("applicant_id", ""),
        "verdict":              state.get("verdict", "REVIEW_REQUIRED"),
        "confidence_score":     state.get("confidence_score", 0.0),
        "explanation":          state.get("explanation", ""),
        "case_id":              state.get("case_id", ""),
        "notification_summary": audit.get("notification_summary"),
        "risk_score":           risk.get("risk_score"),
        "credit_band":          risk.get("credit_band"),
        "dti":                  risk.get("dti"),
    }


def is_state_complete(state: AgentState) -> bool:
    """
    Return True if the state has all required output fields populated.

    Used by the FastAPI route to detect whether the graph completed
    successfully before building the response.

    Args:
        state: AgentState after graph execution.

    Returns:
        True if verdict, confidence_score, explanation, and case_id are
        all non-None. False otherwise.
    """
    return all([
        state.get("verdict") is not None,
        state.get("confidence_score") is not None,
        state.get("explanation") is not None,
        state.get("case_id") is not None,
    ])
