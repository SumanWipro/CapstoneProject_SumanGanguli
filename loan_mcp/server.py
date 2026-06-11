"""
mcp/server.py
=============
FastMCP server for the Loan Approval System.

Responsibilities:
- Create the FastMCP application instance with full metadata
- Register all 6 tools via the @mcp_app.tool() decorator pattern
- Each registered tool wraps the corresponding tool function from mcp/tools/
- Provide the CLI entry point: python -m mcp.server

Architecture note — why FastMCP over a plain HTTP server:
    FastMCP implements the Model Context Protocol (MCP) standard. This means:
    - Tool schemas are auto-generated from Pydantic models and docstrings
    - The LangGraph orchestrator calls tools via a standard MCP client
    - Tools can be swapped to a remote server without changing orchestrator code
    - Each tool is independently discoverable with name, description, and schema

Tool registration pattern:
    Tools are registered by decorating wrapper functions with @mcp_app.tool().
    The wrapper validates input via the tool's Pydantic schema, then delegates
    to the tool implementation function. This keeps the registration layer thin
    and the implementation layer independently testable.

Run with:
    python -m mcp.server
    python mcp/server.py
"""

from __future__ import annotations

from typing import Any

import fastmcp

from config.settings import get_settings
from utils.logger import get_logger

# Tool implementation imports
from loan_mcp.tools.profile_tools import validate_profile, ProfileInput, ProfileOutput
from loan_mcp.tools.risk_tools import calculate_risk, RiskInput, RiskOutput
from loan_mcp.tools.policy_tools import query_policy, PolicyInput, PolicyOutput
from loan_mcp.tools.decision_tools import generate_decision, DecisionInput, DecisionOutput
from loan_mcp.tools.review_action_tools import (
    orchestrate_review_action,
    ReviewActionInput,
    ReviewActionOutput,
)
from loan_mcp.tools.compliance_tools import create_audit, AuditInput, AuditOutput

log      = get_logger(__name__, component="mcp_server")
settings = get_settings()


# ---------------------------------------------------------------------------
# FastMCP application instance
# ---------------------------------------------------------------------------

mcp_app = fastmcp.FastMCP(
    name="LoanApprovalMCPServer",
    host=settings.mcp_host,
    port=settings.mcp_port,
)


# ---------------------------------------------------------------------------
# Tool 1: validate_profile  (Applicant Profile Agent)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="validate_profile",
    description=(
        "Validate applicant profile data. "
        "Checks profile completeness and derives canonical profile metrics. "
        "Returns income_stability_score, employment_risk, "
        "credit_history_summary, and completeness_flags."
    ),
)
def tool_validate_profile(applicant_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for the validate_profile tool.

    Input schema:  ProfileInput  (10 applicant fields)
    Output schema: ProfileOutput (income_stability_score, employment_risk,
                                  credit_history_summary, completeness_flags)

    Args:
        applicant_data: All 10 raw applicant fields from the LoanApplicationRequest.

    Returns:
        ProfileOutput dict. Any non-empty completeness_flags routes the graph
        to early_rejection_node.
    """
    return validate_profile(applicant_data)


# ---------------------------------------------------------------------------
# Tool 2: calculate_risk  (Financial Risk Agent)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="calculate_risk",
    description=(
        "Calculate financial risk metrics for a loan applicant. "
        "Computes DTI ratio, maps credit score to a quality band, derives "
        "a composite risk score (0–100), and identifies active risk flags. "
        "risk_score < 40 → APPROVED range; 40–70 → REVIEW range; > 70 → REJECTED."
    ),
)
def tool_calculate_risk(risk_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for the calculate_risk tool.

    Input schema:  RiskInput  (income, liabilities, credit_score, loan_amount,
                               loan_tenure, employment_risk)
    Output schema: RiskOutput (dti, credit_band, risk_score, risk_flags)

    Args:
        risk_data: Financial fields plus employment_risk from validate_profile output.

    Returns:
        RiskOutput dict with all financial risk metrics.
    """
    return calculate_risk(risk_data)


# ---------------------------------------------------------------------------
# Tool 3: query_policy  (Policy Knowledge Agent — RAG)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="query_policy",
    description=(
        "Retrieve applicable policy clauses from the loan policy knowledge base. "
        "Builds a semantic query from the applicant's risk profile, retrieves "
        "the top-k most relevant chunks from ChromaDB, and uses Claude Sonnet "
        "to identify which clauses apply and produce a policy_summary. "
        "Requires the ChromaDB collection to be populated by running rag.ingest."
    ),
)
def tool_query_policy(policy_query: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for the query_policy tool.

    Input schema:  PolicyInput  (credit_band, dti, employment_risk, loan_amount,
                                 loan_tenure, risk_flags, top_k)
    Output schema: PolicyOutput (chunks, sources, applicable_clauses, policy_summary)

    Args:
        policy_query: Merged context from ProfileOutput + RiskOutput + request fields.

    Returns:
        PolicyOutput dict. policy_summary is passed to generate_decision.
    """
    return query_policy(policy_query)


# ---------------------------------------------------------------------------
# Tool 4: generate_decision  (Loan Decision Agent)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="generate_decision",
    description=(
        "Generate the final loan decision by synthesising all prior agent outputs. "
        "Classifies the application as APPROVED, REJECTED, or REVIEW_REQUIRED. "
        "Returns a confidence score (0.0–1.0) and a plain-English explanation "
        "referencing specific financial metrics for regulatory explainability."
    ),
)
def tool_generate_decision(decision_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for the generate_decision tool.

    Input schema:  DecisionInput  (applicant_id, loan_amount, loan_tenure,
                                   profile_result, risk_result, policy_summary)
    Output schema: DecisionOutput (verdict, confidence, explanation)

    Args:
        decision_data: Aggregated outputs of all three preceding agents.

    Returns:
        DecisionOutput dict with the final verdict, confidence, and explanation.
    """
    return generate_decision(decision_data)


# ---------------------------------------------------------------------------
# Tool 5: orchestrate_review_action  (Review Action Orchestrator)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="orchestrate_review_action",
    description=(
        "Assign explicit review workflow actions for borderline cases. "
        "For REVIEW_REQUIRED outcomes, sets queue assignment, reviewer role, "
        "owner placeholder, SLA due timestamp, and initial lifecycle status. "
        "For non-review outcomes, returns a no-action metadata payload."
    ),
)
def tool_orchestrate_review_action(action_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for review action orchestration.

    Input schema:  ReviewActionInput  (decision context + profile/risk signals)
    Output schema: ReviewActionOutput (action + queue + SLA + lifecycle fields)

    Args:
        action_data: Decision context used to assign review workflow actions.

    Returns:
        ReviewActionOutput dict with action metadata for response and audit.
    """
    return orchestrate_review_action(action_data)


# ---------------------------------------------------------------------------
# Tool 6: create_audit  (Compliance Agent)
# ---------------------------------------------------------------------------

@mcp_app.tool(
    name="create_audit",
    description=(
        "Create the compliance audit record and applicant notification. "
        "Generates a unique Case ID (CASE-YYYYMMDD-NNNN), writes a structured "
        "audit record to audit/logs/ in JSON Lines format, and produces an "
        "applicant-facing notification summary. Always executes — regardless of "
        "verdict — to ensure every decision has a complete audit trail."
    ),
)
def tool_create_audit(case_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP-registered wrapper for the create_audit tool.

    Input schema:  AuditInput  (applicant_id, verdict, confidence, explanation,
                                profile_result, risk_result, timestamp)
    Output schema: AuditOutput (case_id, log_path, notification_summary)

    Args:
        case_data: Complete case data including verdict and prior agent outputs.

    Returns:
        AuditOutput dict with case_id, log_path, and notification_summary.
    """
    return create_audit(case_data)


# ---------------------------------------------------------------------------
# Tool schema introspection utility (for /health and observability)
# ---------------------------------------------------------------------------

def get_registered_tools() -> list[dict[str, str]]:
    """
    Return metadata for all registered MCP tools.

    Used by the GET /health endpoint and the Streamlit workflow page
    to enumerate available tools without importing each tool module.

    Returns:
        List of dicts: [{name, description}, ...]
    """
    return [
        {"name": "validate_profile",   "agent": "ApplicantProfileAgent"},
        {"name": "calculate_risk",     "agent": "FinancialRiskAgent"},
        {"name": "query_policy",       "agent": "PolicyKnowledgeAgent"},
        {"name": "generate_decision",  "agent": "LoanDecisionAgent"},
        {"name": "orchestrate_review_action", "agent": "ReviewActionOrchestrator"},
        {"name": "create_audit",       "agent": "ComplianceAgent"},
    ]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(
        "starting_mcp_server",
        host=settings.mcp_host,
        port=settings.mcp_port,
        tools=get_registered_tools(),
    )
    mcp_app.run(transport="sse")
