"""
api/models/agents.py
====================
Pydantic v2 models for all five agent input payloads and output results.

Responsibilities:
- Define typed, validated input/output contracts for each MCP tool
- Serve as the authoritative schema used by both MCP tools and unit tests
- Provide from_state() class methods so nodes can build payloads cleanly
  from the shared AgentState without manual field picking

Why Pydantic here in addition to TypedDict in orchestrator/state.py?
- orchestrator/state.py TypedDicts are for LangGraph internal state — they
  must remain plain TypedDicts for LangGraph compatibility.
- These Pydantic models are for MCP tool boundaries and test assertions —
  they provide full validation, serialisation, and IDE auto-complete that
  TypedDicts cannot.
- The two representations coexist: nodes use TypedDict; MCP tool inputs
  and outputs use these Pydantic models.

Agent models defined here:
    ProfileAgentInput / ProfileAgentOutput    — Agent 1
    RiskAgentInput    / RiskAgentOutput       — Agent 2
    PolicyAgentInput  / PolicyAgentOutput     — Agent 3
    DecisionAgentInput / DecisionAgentOutput  — Agent 4
    ComplianceAgentInput / ComplianceAgentOutput — Agent 5
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ===========================================================================
# AGENT 1 — Applicant Profile Agent
# ===========================================================================

class ProfileAgentInput(BaseModel):
    """
    Input payload for the Applicant Profile Agent (validate_profile MCP tool).

    Carries all 10 raw applicant fields. The agent validates them and
    classifies the applicant into employment stability bands.

    Attributes:
        applicant_id:          Unique applicant identifier for logging.
        age:                   Applicant age in whole years.
        income:                Annual gross income in INR.
        employment_type:       Declared employment category.
        credit_score:          CIBIL credit score (used only for context; risk
                               scoring is performed by FinancialRiskAgent).
        loan_amount:           Requested loan principal in INR.
        loan_tenure:           Loan repayment period in months.
        existing_liabilities:  Current monthly debt obligations in INR.
        location:              Applicant city or region.
        timestamp:             ISO 8601 submission timestamp.
    """

    applicant_id: str = Field(..., description="Unique applicant identifier")
    age: int = Field(..., ge=0, description="Applicant age in whole years")
    income: float = Field(..., gt=0, description="Annual income in INR")
    employment_type: str = Field(..., description="Employment category string")
    credit_score: int = Field(..., ge=300, le=900, description="CIBIL credit score")
    loan_amount: float = Field(..., gt=0, description="Requested loan amount in INR")
    loan_tenure: int = Field(..., ge=1, description="Loan tenure in months")
    existing_liabilities: float = Field(..., ge=0, description="Monthly liabilities in INR")
    location: str = Field(..., description="Applicant city or region")
    timestamp: str = Field(..., description="ISO 8601 submission timestamp")

    model_config = {"frozen": True}


class ProfileAgentOutput(BaseModel):
    """
    Output produced by the Applicant Profile Agent.

    Attributes:
        income_stability_score:
                           Normalized profile stability score (0-100).
        employment_risk:   Employment risk category derived from
                           employment stability: low | medium | high.
        credit_history_summary:
                           Human-readable summary from credit score.
        completeness_flags:
                           Case-study aligned quality/completeness flags.
        income_stability_score:
                   Normalized profile stability score (0-100).
        employment_risk:   Employment risk category derived from
                   employment band: low | medium | high.
        credit_history_summary:
                   Human-readable summary from credit score.
        completeness_flags:
                   Case-study aligned quality/completeness flags.
    """

    income_stability_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Normalized profile stability score (0-100)",
    )
    employment_risk: Literal["low", "medium", "high"] = Field(
        ...,
        description="Employment risk category derived from employment stability",
    )
    credit_history_summary: str = Field(
        ...,
        description="Human-readable credit history summary",
    )
    completeness_flags: list[str] = Field(
        default_factory=list,
        description="Case-study aligned completeness and validation flags",
    )

    model_config = {"frozen": True}


# ===========================================================================
# AGENT 2 — Financial Risk Agent
# ===========================================================================

class RiskAgentInput(BaseModel):
    """
    Input payload for the Financial Risk Agent (calculate_risk MCP tool).

    Carries the financial fields needed for DTI, credit band, and composite
    risk score calculation. employment_risk is passed from ProfileAgentOutput
    to weight the employment stability component of the risk score.

    Attributes:
        income:                Annual gross income in INR.
        existing_liabilities:  Monthly debt obligations in INR.
        credit_score:          CIBIL credit score.
        loan_amount:           Requested loan principal in INR.
        loan_tenure:           Loan repayment period in months.
        employment_risk:       From ProfileAgentOutput. Used for risk scoring.
    """

    income: float = Field(..., gt=0, description="Annual income in INR")
    existing_liabilities: float = Field(..., ge=0, description="Monthly liabilities in INR")
    credit_score: int = Field(..., ge=300, le=900, description="CIBIL credit score")
    loan_amount: float = Field(..., gt=0, description="Requested loan amount in INR")
    loan_tenure: int = Field(..., ge=1, description="Loan tenure in months")
    employment_risk: Literal["low", "medium", "high"] = Field(
        ...,
        description="Employment risk category from ProfileAgentOutput",
    )

    model_config = {"frozen": True}


class RiskAgentOutput(BaseModel):
    """
    Output produced by the Financial Risk Agent.

    Attributes:
        dti:          Debt-to-income ratio = existing_liabilities / (income/12).
                      Values: < 0.30 low risk; 0.30–0.45 medium; 0.45–0.60
                      high; > 0.60 auto-reject.
        credit_band:  Credit quality band derived from credit_score.
        risk_score:   Composite risk score 0–100. Integrates DTI, credit band,
                      and employment band. Higher = more risk.
                      < 40 → APPROVED; 40–70 → REVIEW; > 70 → REJECTED.
        risk_flags:   List of risk trigger identifiers. Examples:
                      "high_dti", "poor_credit", "unstable_employment",
                      "high_loan_to_income".
    """

    dti: float = Field(
        ...,
        ge=0.0,
        description="Debt-to-income ratio (existing_liabilities / monthly_income)",
    )
    credit_band: Literal["excellent", "good", "fair", "poor"] = Field(
        ...,
        description="Credit quality band derived from CIBIL credit score",
    )
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Composite risk score 0–100. Higher = higher risk.",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="List of risk trigger identifiers. Empty if no triggers.",
    )

    model_config = {"frozen": True}


# ===========================================================================
# AGENT 3 — Policy Knowledge Agent
# ===========================================================================

class PolicyAgentInput(BaseModel):
    """
    Input payload for the Policy Knowledge Agent (query_policy MCP tool).

    Built from the combined ProfileAgentOutput + RiskAgentOutput to construct
    a rich semantic query for ChromaDB retrieval.

    Attributes:
        credit_band:       From RiskAgentOutput.
        dti:               From RiskAgentOutput.
        employment_risk:   From ProfileAgentOutput.
        loan_amount:       From the original request.
        loan_tenure:       From the original request.
        risk_flags:        From RiskAgentOutput. Used to direct policy lookup.
        top_k:             Number of policy chunks to retrieve (default 5).
    """

    credit_band: Literal["excellent", "good", "fair", "poor"] = Field(
        ...,
        description="Credit quality band from RiskAgentOutput",
    )
    dti: float = Field(..., ge=0.0, description="Debt-to-income ratio from RiskAgentOutput")
    employment_risk: Literal["low", "medium", "high"] = Field(
        ...,
        description="Employment risk from ProfileAgentOutput",
    )
    loan_amount: float = Field(..., gt=0, description="Requested loan amount in INR")
    loan_tenure: int = Field(..., ge=1, description="Loan tenure in months")
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Risk flags from RiskAgentOutput to guide policy retrieval",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of policy chunks to retrieve from ChromaDB",
    )

    model_config = {"frozen": True}


class PolicyAgentOutput(BaseModel):
    """
    Output produced by the Policy Knowledge Agent.

    Attributes:
        applicable_clauses:  List of policy clause descriptions that apply to
                             this applicant. Referenced in the decision prompt.
        sources:             Source document filenames for each clause.
        policy_summary:      One-paragraph synthesis of how policies apply,
                             passed as context to the Loan Decision Agent.
    """

    applicable_clauses: list[str] = Field(
        default_factory=list,
        description="Policy clauses applicable to this applicant",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Source document filenames (e.g. credit_policy.txt)",
    )
    policy_summary: str = Field(
        default="",
        description="One-paragraph policy synthesis for the Decision Agent",
    )

    model_config = {"frozen": True}


# ===========================================================================
# AGENT 4 — Loan Decision Agent
# ===========================================================================

class DecisionAgentInput(BaseModel):
    """
    Input payload for the Loan Decision Agent (generate_decision MCP tool).

    Combines all prior agent outputs into a single context for the final
    decision. The Decision Agent receives the full picture: profile validity,
    financial risk metrics, and applicable policy clauses.

    Attributes:
        applicant_id:      For logging and audit correlation.
        loan_amount:       Repeated for the final decision prompt context.
        loan_tenure:       Repeated for the final decision prompt context.
        profile_result:    Full ProfileAgentOutput dict.
        risk_result:       Full RiskAgentOutput dict.
        policy_summary:    policy_summary from PolicyAgentOutput.
    """

    applicant_id: str = Field(..., description="Applicant identifier for logging")
    loan_amount: float = Field(..., gt=0, description="Loan principal in INR")
    loan_tenure: int = Field(..., ge=1, description="Loan tenure in months")
    profile_result: dict[str, Any] = Field(
        ...,
        description="Full ProfileAgentOutput serialised as a dict",
    )
    risk_result: dict[str, Any] = Field(
        ...,
        description="Full RiskAgentOutput serialised as a dict",
    )
    policy_summary: str = Field(
        ...,
        description="Policy synthesis paragraph from PolicyAgentOutput",
    )

    model_config = {"frozen": True}


class DecisionAgentOutput(BaseModel):
    """
    Output produced by the Loan Decision Agent.

    Attributes:
        verdict:      Final loan classification.
        confidence:   Model's confidence in the verdict, 0.0–1.0.
        explanation:  Plain-English rationale (2–4 sentences) for the
                      decision, referencing specific financial factors.
    """

    verdict: Literal["APPROVED", "REJECTED", "REVIEW_REQUIRED"] = Field(
        ...,
        description="Final loan classification",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Decision confidence between 0.0 and 1.0",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description="Plain-English decision rationale (2–4 sentences)",
    )

    model_config = {"frozen": True}


# ===========================================================================
# ACTION ORCHESTRATOR — Review Workflow
# ===========================================================================

class ActionOrchestratorInput(BaseModel):
    """
    Input payload for review action orchestration.

    Attributes:
        applicant_id:      Applicant identifier for audit correlation.
        verdict:           Decision verdict used to decide if review workflow starts.
        confidence:        Decision confidence score from DecisionAgentOutput.
        loan_amount:       Loan amount used for queue routing rules.
        location:          Applicant location used for optional routing rules.
        timestamp:         Original application timestamp used for SLA anchor.
        profile_result:    Profile output for policy/routing context.
        risk_result:       Risk output for queue and SLA classification.
    """

    applicant_id: str = Field(..., description="Applicant identifier")
    verdict: Literal["APPROVED", "REJECTED", "REVIEW_REQUIRED"] = Field(
        ..., description="Decision verdict"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence")
    loan_amount: float = Field(..., gt=0, description="Requested loan amount in INR")
    location: str = Field(..., description="Applicant location")
    timestamp: str = Field(..., description="Original application submission timestamp")
    profile_result: dict[str, Any] = Field(..., description="ProfileAgentOutput as dict")
    risk_result: dict[str, Any] = Field(..., description="RiskAgentOutput as dict")

    model_config = {"frozen": True}


class ActionOrchestratorOutput(BaseModel):
    """
    Output payload for review action orchestration.

    Attributes:
        action_taken:         High-level action selected for this case.
        notification_status:  Current notification dispatch status.
        review_queue:         Queue assignment for manual review.
        manual_review_owner:  Assigned review owner.
        reviewer_role:        Required reviewer role.
        review_due_timestamp: SLA due timestamp in ISO 8601 format.
        review_status:        Current lifecycle status for the case.
        status_transition:    Latest transition label.
        transition_history:   Ordered transition history entries.
    """

    action_taken: str = Field(..., description="Selected action for this case")
    notification_status: str = Field(..., description="Notification dispatch status")
    review_queue: Optional[str] = Field(default=None, description="Assigned review queue")
    manual_review_owner: Optional[str] = Field(default=None, description="Assigned review owner")
    reviewer_role: Optional[str] = Field(default=None, description="Required reviewer role")
    review_due_timestamp: Optional[str] = Field(
        default=None,
        description="Manual review due timestamp in ISO 8601 format",
    )
    review_status: str = Field(..., description="Current review lifecycle status")
    status_transition: str = Field(..., description="Latest lifecycle transition")
    transition_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Ordered lifecycle transition records",
    )

    model_config = {"frozen": True}


# ===========================================================================
# AGENT 5 — Compliance Agent
# ===========================================================================

class ComplianceAgentInput(BaseModel):
    """
    Input payload for the Compliance Agent (create_audit MCP tool).

    Carries the complete case data needed to generate the Case ID, write
    the audit log record, and produce the applicant notification.

    Attributes:
        applicant_id:      Applicant identifier.
        verdict:           Final verdict from DecisionAgentOutput.
        confidence:        Confidence score from DecisionAgentOutput.
        explanation:       Decision rationale from DecisionAgentOutput.
        profile_result:    ProfileAgentOutput dict for audit completeness.
        risk_result:       RiskAgentOutput dict for audit completeness.
        timestamp:         Original application submission timestamp.
        decision_date:     UTC date when the decision was made (YYYY-MM-DD).
    """

    applicant_id: str = Field(..., description="Applicant identifier")
    verdict: Literal["APPROVED", "REJECTED", "REVIEW_REQUIRED"] = Field(
        ..., description="Final loan verdict"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence")
    explanation: str = Field(..., description="Decision rationale text")
    profile_result: dict[str, Any] = Field(..., description="ProfileAgentOutput as dict")
    risk_result: dict[str, Any] = Field(..., description="RiskAgentOutput as dict")
    timestamp: str = Field(..., description="Original application submission timestamp")
    decision_date: str = Field(..., description="Decision date in YYYY-MM-DD format (UTC)")
    action_taken: str = Field(default="NO_ACTION_REQUIRED", description="Selected action")
    notification_status: str = Field(default="NOT_SENT", description="Notification status")
    review_queue: Optional[str] = Field(default=None, description="Assigned review queue")
    manual_review_owner: Optional[str] = Field(default=None, description="Current review owner")
    reviewer_role: Optional[str] = Field(default=None, description="Assigned reviewer role")
    review_due_timestamp: Optional[str] = Field(
        default=None,
        description="Manual review due timestamp in ISO 8601",
    )
    review_status: str = Field(default="NOT_REQUIRED", description="Review lifecycle status")
    status_transition: str = Field(default="NONE", description="Latest lifecycle transition")
    transition_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Lifecycle transition history entries",
    )

    model_config = {"frozen": True}


class ComplianceAgentOutput(BaseModel):
    """
    Output produced by the Compliance Agent.

    Attributes:
        case_id:               Unique audit Case ID. Format: CASE-YYYYMMDD-NNNN.
        log_path:              Absolute path to the audit JSONL file written.
        notification_summary:  Applicant-facing notification text (3–5 sentences).
    """

    case_id: str = Field(
        ...,
        min_length=1,
        description="Unique Case ID. Format: CASE-YYYYMMDD-NNNN.",
        examples=["CASE-20240115-0042"],
    )
    log_path: str = Field(
        ...,
        description="Absolute path to the audit JSONL file.",
        examples=["./audit/logs/2024-01-15.jsonl"],
    )
    notification_summary: str = Field(
        ...,
        min_length=1,
        description="Applicant-facing notification text (3–5 sentences).",
    )

    model_config = {"frozen": True}
