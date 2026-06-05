"""
mcp/tools/risk_tools.py
========================
MCP Tool: calculate_risk
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py → financial_risk_node

Responsibility:
    Expose the FinancialRiskAgent as a validated, schema-documented
    MCP tool callable by the LangGraph orchestrator.

Tool contract:
    Name:   calculate_risk
    Input:  RiskInput  — income, liabilities, credit_score, loan_amount,
                         loan_tenure, employment_band
    Output: RiskOutput — dti, credit_band, risk_score, risk_flags
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.financial_risk_agent import FinancialRiskAgent
from utils.logger import get_logger

log = get_logger(__name__, component="risk_tools")


# ---------------------------------------------------------------------------
# Tool input / output schemas
# ---------------------------------------------------------------------------

class RiskInput(BaseModel):
    """
    Input schema for the calculate_risk MCP tool.

    employment_band is passed from the ProfileOutput of validate_profile —
    the risk score formula requires the stability band, not the raw
    employment_type string.
    """

    income: float = Field(
        ..., gt=0,
        description="Annual gross income in INR",
    )
    existing_liabilities: float = Field(
        ..., ge=0,
        description="Current monthly debt obligations in INR",
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
    employment_band: str = Field(
        ...,
        description="Employment stability band from ProfileOutput: stable | moderate | unstable",
    )


class RiskOutput(BaseModel):
    """
    Output schema for the calculate_risk MCP tool.

    Maps 1:1 to the RiskResult TypedDict in orchestrator/state.py and
    the RiskAgentOutput Pydantic model in api/models/agents.py.
    """

    dti: float = Field(
        ..., ge=0.0,
        description="Debt-to-income ratio = existing_liabilities / (income/12)",
    )
    credit_band: str = Field(
        ...,
        description="Credit quality band: excellent | good | fair | poor",
    )
    risk_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Composite risk score 0–100. Higher = higher risk.",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Active risk trigger codes. Empty if no triggers.",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def calculate_risk(risk_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP Tool: calculate_risk

    Calculates financial risk metrics by delegating to FinancialRiskAgent.

    Called by:  orchestrator/nodes.py → financial_risk_node
    Delegates:  agents.financial_risk_agent.FinancialRiskAgent.invoke()

    Args:
        risk_data: Dict matching RiskInput schema.

    Returns:
        Dict matching RiskOutput schema:
            dti (float), credit_band (str), risk_score (float),
            risk_flags (list[str])

    Raises:
        ValidationError:     If risk_data fails RiskInput schema.
        ClientError:         If Bedrock call fails after 3 retries.
        json.JSONDecodeError: If Claude returns non-JSON output.
    """
    log.info(
        "calculate_risk_tool_called",
        income=risk_data.get("income"),
        credit_score=risk_data.get("credit_score"),
    )

    validated = RiskInput(**risk_data)
    agent     = FinancialRiskAgent()
    result    = agent.invoke(validated.model_dump())
    output    = RiskOutput(**result)

    log.info(
        "calculate_risk_tool_complete",
        dti=output.dti,
        credit_band=output.credit_band,
        risk_score=output.risk_score,
        risk_flags=output.risk_flags,
    )

    return output.model_dump()
