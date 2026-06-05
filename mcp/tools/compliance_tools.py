"""
mcp/tools/compliance_tools.py
==============================
MCP Tool: create_audit
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py → compliance_node

Responsibility:
    Expose the ComplianceAgent as a validated, schema-documented
    MCP tool callable by the LangGraph orchestrator.

Tool contract:
    Name:   create_audit
    Input:  AuditInput  — applicant_id, verdict, confidence, explanation,
                          profile_result, risk_result, timestamp
    Output: AuditOutput — case_id, log_path, notification_summary

This tool always executes — regardless of verdict — because every loan
decision (APPROVED, REJECTED, REVIEW_REQUIRED) requires an audit record
for regulatory compliance. The compliance node also runs on early rejection
paths to ensure no application is processed without an audit trail.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.compliance_agent import ComplianceAgent
from utils.logger import get_logger

log = get_logger(__name__, component="compliance_tools")


# ---------------------------------------------------------------------------
# Tool input / output schemas
# ---------------------------------------------------------------------------

class AuditInput(BaseModel):
    """
    Input schema for the create_audit MCP tool.

    Carries the complete case data required to:
    1. Generate the unique Case ID
    2. Write the structured audit record to audit/logs/
    3. Produce the applicant notification via Claude Sonnet
    """

    applicant_id: str = Field(
        ...,
        description="Unique applicant identifier",
    )
    verdict: str = Field(
        ...,
        description="Final loan verdict: APPROVED | REJECTED | REVIEW_REQUIRED",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Decision confidence score 0.0–1.0",
    )
    explanation: str = Field(
        ...,
        description="Plain-English decision rationale from LoanDecisionAgent",
    )
    profile_result: dict[str, Any] = Field(
        ...,
        description="Full ProfileOutput dict — stored in audit record",
    )
    risk_result: dict[str, Any] = Field(
        ...,
        description="Full RiskOutput dict — stored in audit record and used for metrics",
    )
    timestamp: str = Field(
        ...,
        description="Original application submission timestamp (ISO 8601)",
    )


class AuditOutput(BaseModel):
    """
    Output schema for the create_audit MCP tool.

    Maps 1:1 to the AuditRecord TypedDict in orchestrator/state.py and
    the ComplianceAgentOutput Pydantic model in api/models/agents.py.
    """

    case_id: str = Field(
        ...,
        description="Unique Case ID. Format: CASE-YYYYMMDD-NNNN",
        examples=["CASE-20240115-0042"],
    )
    log_path: str = Field(
        ...,
        description="Absolute path to the audit JSONL file written",
    )
    notification_summary: str = Field(
        ...,
        description="Applicant-facing notification text (3–5 sentences)",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def create_audit(case_data: dict[str, Any]) -> dict[str, Any]:
    """
    MCP Tool: create_audit

    Creates the audit trail and notification by delegating to ComplianceAgent.

    Called by:  orchestrator/nodes.py → compliance_node
                (also called by early_rejection_node)
    Delegates:  agents.compliance_agent.ComplianceAgent.invoke()
                which writes to audit/logs/ via utils.audit

    This tool always succeeds or raises — it never returns partial output.
    If the audit write fails, the OSError propagates so the orchestrator
    can log and handle the error rather than silently losing the record.

    Args:
        case_data: Dict matching AuditInput schema.

    Returns:
        Dict matching AuditOutput schema:
            case_id (str), log_path (str), notification_summary (str)

    Raises:
        ValidationError: If case_data fails AuditInput schema.
        ClientError:     If Bedrock call fails after 3 retries.
        OSError:         If audit log directory cannot be written.
    """
    log.info(
        "create_audit_tool_called",
        applicant_id=case_data.get("applicant_id"),
        verdict=case_data.get("verdict"),
    )

    validated = AuditInput(**case_data)
    agent     = ComplianceAgent()
    result    = agent.invoke(validated.model_dump())
    output    = AuditOutput(**result)

    log.info(
        "create_audit_tool_complete",
        applicant_id=case_data.get("applicant_id"),
        case_id=output.case_id,
        log_path=output.log_path,
    )

    return output.model_dump()
