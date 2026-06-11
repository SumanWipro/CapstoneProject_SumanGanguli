"""
mcp/tools/profile_tools.py
===========================
MCP Tool: validate_profile
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py → applicant_profile_node

Responsibility:
    Expose the ApplicantProfileAgent as a validated, schema-documented
    MCP tool callable by the LangGraph orchestrator.

Tool contract:
    Name:   validate_profile
    Input:  ProfileInput — all 10 applicant fields
    Output: ProfileOutput — income_stability_score,
                            employment_risk, credit_history_summary,
                            completeness_flags

Schema design:
    Input and output are typed Pydantic models registered on the FastMCP
    app. FastMCP auto-generates the JSON Schema exposed in the MCP tool
    manifest, giving the orchestrator full type information at tool-call
    time without any manual schema authoring.

Why wrap the agent in an MCP tool:
    The orchestrator node never imports agents directly. Every agent call
    goes through an MCP tool. This decouples node logic from agent
    implementation — an agent can be replaced, mocked, or versioned
    without changing the orchestrator graph.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.applicant_profile_agent import ApplicantProfileAgent
from utils.logger import get_logger

log = get_logger(__name__, component="profile_tools")


# ---------------------------------------------------------------------------
# Tool input / output schemas
# ---------------------------------------------------------------------------

class ProfileInput(BaseModel):
    """
    Input schema for the validate_profile MCP tool.

    All 10 raw applicant fields from the LoanApplicationRequest are passed
    verbatim. The agent performs domain-level validation (age eligibility,
    employment band, income consistency) — Pydantic provides type safety.
    """

    applicant_id: str = Field(
        ...,
        description="Unique applicant identifier e.g. APP-2024-001",
    )
    age: int = Field(
        ..., ge=0, le=150,
        description="Applicant age in whole years",
    )
    income: float = Field(
        ..., gt=0,
        description="Annual gross income in INR",
    )
    employment_type: str = Field(
        ...,
        description="Employment category: salaried | self_employed | contract | government | unemployed | student",
    )
    credit_score: int = Field(
        ..., ge=300, le=900,
        description="CIBIL credit score 300–900",
    )
    loan_amount: float = Field(
        ..., gt=0,
        description="Requested loan principal in INR",
    )
    loan_tenure: int = Field(
        ..., ge=1, le=360,
        description="Loan repayment period in months",
    )
    existing_liabilities: float = Field(
        ..., ge=0,
        description="Monthly debt obligations in INR",
    )
    location: str = Field(
        ...,
        description="Applicant city or region",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 application submission timestamp",
    )


class ProfileOutput(BaseModel):
    """
    Output schema for the validate_profile MCP tool.

    Maps 1:1 to the ProfileResult TypedDict in orchestrator/state.py and
    the ProfileAgentOutput Pydantic model in api/models/agents.py.
    """

    income_stability_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Normalized profile stability score (0-100)",
    )
    employment_risk: str = Field(
        ...,
        description="Employment risk category: low | medium | high",
    )
    credit_history_summary: str = Field(
        ...,
        description="Human-readable summary derived from credit score",
    )
    completeness_flags: list[str] = Field(
        default_factory=list,
        description="Case-study aligned completeness and validation flags",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def validate_profile(applicant_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP Tool: validate_profile

    Validates applicant profile data by delegating to ApplicantProfileAgent.

    Called by:  orchestrator/nodes.py → applicant_profile_node
    Delegates:  agents.applicant_profile_agent.ApplicantProfileAgent.invoke()

    The agent is instantiated fresh per call. This is intentional —
    agents are stateless (all state lives in AgentState), so a fresh
    instance per call avoids any shared-state issues across concurrent
    requests.

    Args:
        applicant_data: Dict matching ProfileInput schema. All 10 fields
                        from the original LoanApplicationRequest.

    Returns:
        Dict matching ProfileOutput schema:
            income_stability_score (float), employment_risk (str),
            credit_history_summary (str), completeness_flags (list)

    Raises:
        ValidationError: If applicant_data fails ProfileInput schema.
        ClientError:     If the Bedrock call fails after 3 retries.
        json.JSONDecodeError: If Claude returns non-JSON output.
    """
    log.info(
        "validate_profile_tool_called",
        applicant_id=applicant_data.get("applicant_id"),
    )

    # Validate input schema
    validated = ProfileInput(**applicant_data)

    # Delegate to agent
    agent  = ApplicantProfileAgent()
    result = agent.invoke(validated.model_dump())

    # Validate output schema before returning
    output = ProfileOutput(**result)

    log.info(
        "validate_profile_tool_complete",
        applicant_id=applicant_data.get("applicant_id"),
        employment_risk=output.employment_risk,
        income_stability_score=output.income_stability_score,
    )

    return output.model_dump()
