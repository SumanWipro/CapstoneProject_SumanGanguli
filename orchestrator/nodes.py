"""
orchestrator/nodes.py
=====================
LangGraph node functions for the Loan Approval pipeline.

Responsibilities:
- One function per graph node (7 total)
- Each node receives the full AgentState, calls the appropriate MCP tool,
  writes results back into state, and returns a partial state dict
- Nodes NEVER import or call agents directly — always via MCP tool functions
- Error handling: exceptions are caught, stored in state["error"], and the
  graph continues to compliance_node for audit logging

Node execution order:
    validate_input_node          — field presence + hard eligibility checks
        ↓ always
    applicant_profile_node       — validate_profile MCP tool
        ↓ profile_gate (conditional)
        ├─ (valid)   → financial_risk_node
        └─ (invalid) → early_rejection_node
    financial_risk_node          — calculate_risk MCP tool
        ↓
    policy_knowledge_node        — query_policy MCP tool
        ↓
    loan_decision_node           — generate_decision MCP tool
        ↓                              ↑ early_rejection_node also feeds here
    compliance_node              — create_audit MCP tool
        ↓
    END

Design decision — nodes call MCP tool functions directly (not over HTTP):
    In production, nodes would call tools via an MCP client over the network.
    For this capstone, the MCP tool functions are called in-process for
    simplicity and speed. The abstraction boundary is preserved — nodes
    import from mcp.tools, not from agents — so replacing with HTTP calls
    only requires changing the import and call site in each node function.
"""

from __future__ import annotations

from orchestrator.state import AgentState
from utils.logger import get_logger

# MCP tool imports — nodes only import tools, never agents directly
from mcp.tools.profile_tools   import validate_profile
from mcp.tools.risk_tools      import calculate_risk
from mcp.tools.policy_tools    import query_policy
from mcp.tools.decision_tools  import generate_decision
from mcp.tools.compliance_tools import create_audit

log = get_logger(__name__, component="nodes")

# Required input fields — presence checked by validate_input_node
_REQUIRED_FIELDS = [
    "applicant_id", "age", "income", "employment_type",
    "credit_score", "loan_amount", "loan_tenure",
    "existing_liabilities", "location", "timestamp",
]


# ===========================================================================
# Node 1: validate_input
# ===========================================================================

def validate_input_node(state: AgentState) -> dict:
    """
    Validate that all required input fields are present and non-empty.

    This is a pure Python check — no LLM call, no MCP tool. It catches
    structurally invalid requests before any agent is invoked.

    Hard eligibility checks performed here (not delegated to the profile agent):
    - All 10 required fields must be present and non-None
    - age must be an integer in [18, 70]
    - credit_score must be in [300, 900]

    If any check fails, sets early_exit=True and error to a description.
    The graph then routes directly to early_rejection_node → compliance_node.

    Args:
        state: Initial AgentState from LoanApplicationRequest.to_agent_state()

    Returns:
        Partial state dict. If valid: {"early_exit": False}.
        If invalid: {"early_exit": True, "error": "<description>"}.
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("validate_input_node_called", applicant_id=applicant_id)

    # Check all required fields are present and non-None
    missing = [f for f in _REQUIRED_FIELDS if state.get(f) is None]
    if missing:
        msg = f"Missing required fields: {missing}"
        log.warning("validate_input_failed_missing_fields",
                    applicant_id=applicant_id, missing=missing)
        return {"early_exit": True, "error": msg}

    # Hard eligibility: age
    age = state.get("age", 0)
    if not (18 <= age <= 70):
        msg = f"Age {age} is outside the eligible range [18, 70]."
        log.warning("validate_input_failed_age",
                    applicant_id=applicant_id, age=age)
        return {"early_exit": True, "error": msg}

    # Hard eligibility: credit score
    credit_score = state.get("credit_score", 0)
    if not (300 <= credit_score <= 900):
        msg = f"Credit score {credit_score} is outside valid range [300, 900]."
        log.warning("validate_input_failed_credit_score",
                    applicant_id=applicant_id, credit_score=credit_score)
        return {"early_exit": True, "error": msg}

    log.info("validate_input_node_passed", applicant_id=applicant_id)
    return {"early_exit": False}


# ===========================================================================
# Node 2: applicant_profile_node
# ===========================================================================

def applicant_profile_node(state: AgentState) -> dict:
    """
    Call the validate_profile MCP tool and write ProfileResult into state.

    Builds the ProfileInput payload from the 10 raw applicant fields,
    calls the tool, and returns the result as profile_result.

    If the agent marks the profile invalid (e.g. age_eligible=False,
    income_consistent=False), sets early_exit=True so the graph routes
    to early_rejection_node.

    Args:
        state: AgentState with all input fields present (guaranteed by
               validate_input_node running before this node).

    Returns:
        {"profile_result": ProfileResult, "early_exit": bool}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("applicant_profile_node_called", applicant_id=applicant_id)

    try:
        applicant_data = {
            "applicant_id":         state["applicant_id"],
            "age":                  state["age"],
            "income":               state["income"],
            "employment_type":      state["employment_type"],
            "credit_score":         state["credit_score"],
            "loan_amount":          state["loan_amount"],
            "loan_tenure":          state["loan_tenure"],
            "existing_liabilities": state["existing_liabilities"],
            "location":             state["location"],
            "timestamp":            state["timestamp"],
        }

        profile_result = validate_profile(applicant_data)

        # If profile invalid, flag for early exit
        early_exit = not profile_result.get("valid", False)
        if early_exit:
            log.warning(
                "applicant_profile_invalid",
                applicant_id=applicant_id,
                flags=profile_result.get("flags", []),
            )

        log.info(
            "applicant_profile_node_complete",
            applicant_id=applicant_id,
            valid=profile_result.get("valid"),
            employment_band=profile_result.get("employment_band"),
        )
        return {"profile_result": profile_result, "early_exit": early_exit}

    except Exception as exc:
        log.error("applicant_profile_node_error",
                  applicant_id=applicant_id, error=str(exc))
        return {
            "early_exit": True,
            "error": f"Profile validation failed: {exc}",
        }


# ===========================================================================
# Node 3: financial_risk_node
# ===========================================================================

def financial_risk_node(state: AgentState) -> dict:
    """
    Call the calculate_risk MCP tool and write RiskResult into state.

    Builds the RiskInput payload combining financial fields from the
    original request with employment_band from profile_result.

    Args:
        state: AgentState with profile_result populated (guaranteed by
               the graph edge ordering: applicant_profile_node → this node).

    Returns:
        {"risk_result": RiskResult}
        On error: {"risk_result": None, "error": str}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("financial_risk_node_called", applicant_id=applicant_id)

    try:
        profile_result = state.get("profile_result") or {}
        employment_band = profile_result.get("employment_band", "stable")

        risk_data = {
            "income":               state["income"],
            "existing_liabilities": state["existing_liabilities"],
            "credit_score":         state["credit_score"],
            "loan_amount":          state["loan_amount"],
            "loan_tenure":          state["loan_tenure"],
            "employment_band":      employment_band,
        }

        risk_result = calculate_risk(risk_data)

        log.info(
            "financial_risk_node_complete",
            applicant_id=applicant_id,
            dti=risk_result.get("dti"),
            credit_band=risk_result.get("credit_band"),
            risk_score=risk_result.get("risk_score"),
        )
        return {"risk_result": risk_result}

    except Exception as exc:
        log.error("financial_risk_node_error",
                  applicant_id=applicant_id, error=str(exc))
        return {"error": f"Risk calculation failed: {exc}"}


# ===========================================================================
# Node 4: policy_knowledge_node
# ===========================================================================

def policy_knowledge_node(state: AgentState) -> dict:
    """
    Call the query_policy MCP tool and write PolicyChunks into state.

    Builds the PolicyInput payload from risk_result and profile_result,
    plus the original loan_amount and loan_tenure from state.

    Args:
        state: AgentState with risk_result and profile_result populated.

    Returns:
        {"policy_chunks": PolicyChunks}
        On error: {"policy_chunks": None, "error": str}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("policy_knowledge_node_called", applicant_id=applicant_id)

    try:
        risk_result    = state.get("risk_result") or {}
        profile_result = state.get("profile_result") or {}

        policy_query = {
            "credit_band":     risk_result.get("credit_band", "fair"),
            "dti":             risk_result.get("dti", 0.0),
            "employment_band": profile_result.get("employment_band", "stable"),
            "loan_amount":     state["loan_amount"],
            "loan_tenure":     state["loan_tenure"],
            "risk_flags":      risk_result.get("risk_flags", []),
        }

        policy_chunks = query_policy(policy_query)

        log.info(
            "policy_knowledge_node_complete",
            applicant_id=applicant_id,
            clauses=len(policy_chunks.get("applicable_clauses", [])),
            sources=policy_chunks.get("sources", []),
        )
        return {"policy_chunks": policy_chunks}

    except Exception as exc:
        log.error("policy_knowledge_node_error",
                  applicant_id=applicant_id, error=str(exc))
        # Non-fatal: proceed with empty policy context rather than failing
        return {
            "policy_chunks": {
                "chunks": [], "sources": [],
                "applicable_clauses": [],
                "policy_summary": "Policy lookup unavailable.",
            },
            "error": f"Policy retrieval warning: {exc}",
        }


# ===========================================================================
# Node 5: loan_decision_node
# ===========================================================================

def loan_decision_node(state: AgentState) -> dict:
    """
    Call the generate_decision MCP tool and write the final verdict into state.

    Aggregates all prior agent outputs into the DecisionInput payload and
    promotes the result fields to the top-level state output group.

    Args:
        state: AgentState with profile_result, risk_result, and policy_chunks
               all populated.

    Returns:
        {"decision_result": DecisionResult,
         "verdict": str, "confidence_score": float, "explanation": str}
        On error: {"verdict": "REVIEW_REQUIRED", "error": str}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("loan_decision_node_called", applicant_id=applicant_id)

    try:
        policy_chunks  = state.get("policy_chunks") or {}
        policy_summary = policy_chunks.get("policy_summary",
                                           "No policy context available.")

        decision_data = {
            "applicant_id":   applicant_id,
            "loan_amount":    state["loan_amount"],
            "loan_tenure":    state["loan_tenure"],
            "profile_result": state.get("profile_result") or {},
            "risk_result":    state.get("risk_result") or {},
            "policy_summary": policy_summary,
        }

        decision_result = generate_decision(decision_data)

        log.info(
            "loan_decision_node_complete",
            applicant_id=applicant_id,
            verdict=decision_result.get("verdict"),
            confidence=decision_result.get("confidence"),
        )

        return {
            "decision_result": decision_result,
            # Promote to top-level output group for LoanDecisionResponse
            "verdict":         decision_result.get("verdict", "REVIEW_REQUIRED"),
            "confidence_score":decision_result.get("confidence", 0.5),
            "explanation":     decision_result.get("explanation", ""),
        }

    except Exception as exc:
        log.error("loan_decision_node_error",
                  applicant_id=applicant_id, error=str(exc))
        return {
            "verdict":          "REVIEW_REQUIRED",
            "confidence_score": 0.5,
            "explanation":      "Decision could not be determined automatically.",
            "error":            f"Decision generation failed: {exc}",
        }


# ===========================================================================
# Node 6: early_rejection_node
# ===========================================================================

def early_rejection_node(state: AgentState) -> dict:
    """
    Short-circuit node for applications that fail hard eligibility checks.

    Invoked when profile_gate routes here due to early_exit=True. Sets
    REJECTED verdict and derives a human-readable explanation from the
    error or profile flags — without any LLM call (zero agent cost).

    Args:
        state: AgentState with early_exit=True. error or profile_result.flags
               contains the reason for rejection.

    Returns:
        {"verdict": "REJECTED", "confidence_score": 0.95,
         "explanation": str, "decision_result": {...}}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("early_rejection_node_called", applicant_id=applicant_id)

    # Build explanation from error message or profile flags
    error_msg      = state.get("error", "")
    profile_result = state.get("profile_result") or {}
    flags          = profile_result.get("flags", [])

    if error_msg:
        explanation = f"Application rejected: {error_msg}"
    elif flags:
        explanation = (
            f"Application rejected at eligibility screening. "
            f"Issues detected: {'; '.join(flags)}."
        )
    else:
        explanation = (
            "Application rejected at eligibility screening. "
            "The applicant does not meet the minimum eligibility criteria."
        )

    decision_result = {
        "verdict":     "REJECTED",
        "confidence":  0.95,   # Hard rule → high confidence
        "explanation": explanation,
    }

    log.info(
        "early_rejection_node_complete",
        applicant_id=applicant_id,
        explanation=explanation[:80],
    )

    return {
        "decision_result":  decision_result,
        "verdict":          "REJECTED",
        "confidence_score": 0.95,
        "explanation":      explanation,
    }


# ===========================================================================
# Node 7: compliance_node
# ===========================================================================

def compliance_node(state: AgentState) -> dict:
    """
    Call the create_audit MCP tool and write the AuditRecord into state.

    Always executes — regardless of verdict or early_exit flag. Ensures
    every application has a complete audit trail including REJECTED and
    error cases.

    Args:
        state: AgentState with verdict, confidence_score, and explanation
               populated by either loan_decision_node or early_rejection_node.

    Returns:
        {"audit_record": AuditRecord, "case_id": str}
        On error: {"case_id": "CASE-ERROR", "error": str}
    """
    applicant_id = state.get("applicant_id", "UNKNOWN")
    log.info("compliance_node_called",
             applicant_id=applicant_id, verdict=state.get("verdict"))

    try:
        case_data = {
            "applicant_id":   applicant_id,
            "verdict":        state.get("verdict", "REVIEW_REQUIRED"),
            "confidence":     state.get("confidence_score", 0.5),
            "explanation":    state.get("explanation", ""),
            "profile_result": state.get("profile_result") or {},
            "risk_result":    state.get("risk_result") or {},
            "timestamp":      state.get("timestamp", ""),
        }

        audit_record = create_audit(case_data)

        log.info(
            "compliance_node_complete",
            applicant_id=applicant_id,
            case_id=audit_record.get("case_id"),
        )

        return {
            "audit_record": audit_record,
            "case_id":      audit_record.get("case_id", ""),
        }

    except Exception as exc:
        log.error("compliance_node_error",
                  applicant_id=applicant_id, error=str(exc))
        return {
            "case_id": "CASE-ERROR",
            "error":   f"Audit record creation failed: {exc}",
        }
