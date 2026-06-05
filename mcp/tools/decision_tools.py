"""
mcp/tools/decision_tools.py
============================
MCP Tool: generate_decision
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py → loan_decision_node

Responsibility:
    Expose the LoanDecisionAgent as a validated, schema-documented
    MCP tool callable by the LangGraph orchestrator.

Tool contract:
    Name:   generate_decision
    Input:  DecisionInput  — applicant_id, loan_amount, loan_tenure,
                             profile_result, risk_result, policy_summary
    Output: DecisionOutput — verdict, confidence, explanation

This tool is the convergence point of the pipeline: it receives the
aggregated outputs of all three preceding agents (Profile, Risk, Policy)
and produces the final classification.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.loan_decision_agent import LoanDecisionAgent
from utils.logger import get_logger

log = get_logger(__name__, component="decision_tools")


# ---------------------------------------------------------------------------
# Tool input / output schemas
# ---------------------------------------------------------------------------

class DecisionInput(BaseModel):
    """
    Input schema for the generate_decision MCP tool.

    Aggregates the outputs of all three prior agents into a single
    context payload for the Loan Decision Agent.
    """

    applicant_id: str = Field(
        ...,
        description="Applicant identifier for logging and explanation context",
    )
    loan_amount: float = Field(
        ..., gt=0,
        description="Requested loan principal in INR",
    )
    loan_tenure: int = Field(
        ..., ge=1, le=360,
        description="Loan repayment period in months",
    )
    profile_result: dict[str, Any] = Field(
        ...,
        description="Full ProfileOutput dict from validate_profile tool",
    )
    risk_result: dict[str, Any] = Field(
        ...,
        description="Full RiskOutput dict from calculate_risk tool",
    )
    policy_summary: str = Field(
        ...,
        description="policy_summary paragraph from PolicyOutput.query_policy tool",
    )


class DecisionOutput(BaseModel):
    """
    Output schema for the generate_decision MCP tool.

    Maps 1:1 to the DecisionResult TypedDict in orchestrator/state.py and
    the DecisionAgentOutput Pydantic model in api/models/agents.py.
    """

    verdict: str = Field(
        ...,
        description="Final loan classification: APPROVED | REJECTED | REVIEW_REQUIRED",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Decision confidence between 0.0 and 1.0",
    )
    explanation: str = Field(
        ...,
        description="Plain-English decision rationale (2–4 sentences)",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def generate_decision(decision_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP Tool: generate_decision

    Generates the final loan decision by delegating to LoanDecisionAgent.

    Called by:  orchestrator/nodes.py → loan_decision_node
    Delegates:  agents.loan_decision_agent.LoanDecisionAgent.invoke()

    Args:
        decision_data: Dict matching DecisionInput schema. Contains the
                       aggregated outputs of the three preceding agents.

    Returns:
        Dict matching DecisionOutput schema:
            verdict (str), confidence (float), explanation (str)

    Raises:
        ValidationError:     If decision_data fails DecisionInput schema.
        ClientError:         If Bedrock call fails after 3 retries.
        json.JSONDecodeError: If Claude returns non-JSON output.
    """
    log.info(
        "generate_decision_tool_called",
        applicant_id=decision_data.get("applicant_id"),
    )

    validated = DecisionInput(**decision_data)
    agent     = LoanDecisionAgent()
    result    = agent.invoke(validated.model_dump())
    output    = DecisionOutput(**result)

    log.info(
        "generate_decision_tool_complete",
        applicant_id=decision_data.get("applicant_id"),
        verdict=output.verdict,
        confidence=output.confidence,
    )

    return output.model_dump()
