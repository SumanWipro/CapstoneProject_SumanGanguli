"""
mcp/tools/policy_tools.py
==========================
MCP Tool: query_policy
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py → policy_knowledge_node

Responsibility:
    Expose the PolicyKnowledgeAgent (RAG + Claude) as a validated,
    schema-documented MCP tool callable by the LangGraph orchestrator.

Tool contract:
    Name:   query_policy
    Input:  PolicyInput  — credit_band, dti, employment_risk, loan_amount,
                           loan_tenure, risk_flags, top_k
    Output: PolicyOutput — chunks, sources, applicable_clauses, policy_summary

Why risk_flags are passed through:
    The policy search query is richer when risk flags are included. For
    example, a "high_dti" flag steers retrieval toward DTI threshold
    policy clauses rather than general income guidelines.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.policy_knowledge_agent import PolicyKnowledgeAgent
from utils.logger import get_logger

log = get_logger(__name__, component="policy_tools")


# ---------------------------------------------------------------------------
# Tool input / output schemas
# ---------------------------------------------------------------------------

class PolicyInput(BaseModel):
    """
    Input schema for the query_policy MCP tool.

    Built from the outputs of validate_profile (employment_risk) and
    calculate_risk (credit_band, dti, risk_flags) combined with the
    original request fields (loan_amount, loan_tenure).
    """

    credit_band: str = Field(
        ...,
        description="Credit quality band from RiskOutput: excellent | good | fair | poor",
    )
    dti: float = Field(
        ..., ge=0.0,
        description="Debt-to-income ratio from RiskOutput",
    )
    employment_risk: str = Field(
        ...,
        description="Employment risk from ProfileOutput: low | medium | high",
    )
    loan_amount: float = Field(
        ..., gt=0,
        description="Requested loan amount in INR",
    )
    loan_tenure: int = Field(
        ..., ge=1, le=360,
        description="Loan repayment period in months",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Active risk trigger codes from RiskOutput",
    )
    top_k: int = Field(
        default=5, ge=1, le=20,
        description="Number of policy chunks to retrieve from ChromaDB",
    )


class PolicyOutput(BaseModel):
    """
    Output schema for the query_policy MCP tool.

    Maps 1:1 to the PolicyChunks TypedDict in orchestrator/state.py and
    the PolicyAgentOutput Pydantic model in api/models/agents.py.
    """

    chunks: list[str] = Field(
        default_factory=list,
        description="Raw policy text segments retrieved from ChromaDB",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Source document filenames e.g. credit_policy.txt",
    )
    applicable_clauses: list[str] = Field(
        default_factory=list,
        description="Claude-identified clauses directly applicable to this applicant",
    )
    policy_summary: str = Field(
        default="",
        description="One-paragraph synthesis passed to the Loan Decision Agent",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def query_policy(policy_query: dict[str, Any]) -> dict[str, Any]:
    """
    MCP Tool: query_policy

    Retrieves applicable policy context by delegating to PolicyKnowledgeAgent.

    Called by:  orchestrator/nodes.py → policy_knowledge_node
    Delegates:  agents.policy_knowledge_agent.PolicyKnowledgeAgent.invoke()
                which internally calls rag.policy_search.search() + Claude

    Args:
        policy_query: Dict matching PolicyInput schema. Merged dict of
                      ProfileOutput fields, RiskOutput fields, and
                      original request fields.

    Returns:
        Dict matching PolicyOutput schema:
            chunks (list), sources (list), applicable_clauses (list),
            policy_summary (str)

    Raises:
        ValidationError: If policy_query fails PolicyInput schema.
        ValueError:      If ChromaDB collection not populated.
        ClientError:     If Bedrock call fails after 3 retries.
    """
    log.info(
        "query_policy_tool_called",
        credit_band=policy_query.get("credit_band"),
        dti=policy_query.get("dti"),
        top_k=policy_query.get("top_k", 5),
    )

    validated = PolicyInput(**policy_query)
    agent     = PolicyKnowledgeAgent()
    result    = agent.invoke(validated.model_dump())
    output    = PolicyOutput(**result)

    log.info(
        "query_policy_tool_complete",
        chunks_returned=len(output.chunks),
        clauses_found=len(output.applicable_clauses),
        sources=output.sources,
    )

    return output.model_dump()
