"""
mcp/tools/review_action_tools.py
================================
MCP Tool: orchestrate_review_action
Server:   LoanApprovalMCPServer
Node:     orchestrator/nodes.py -> review_action_node

Responsibility:
    Deterministically assign manual-review workflow actions for
    REVIEW_REQUIRED cases. Non-review verdicts receive a no-op action payload
    so downstream response and audit schemas stay shape-consistent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from config.settings import get_settings
from utils.logger import get_logger

log = get_logger(__name__, component="review_action_tools")
settings = get_settings()


class ReviewActionInput(BaseModel):
    """Input schema for review-action orchestration."""

    applicant_id: str = Field(..., description="Applicant identifier")
    verdict: str = Field(..., description="Final decision verdict")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence")
    loan_amount: float = Field(..., gt=0, description="Requested loan amount in INR")
    location: str = Field(..., description="Applicant location")
    timestamp: str = Field(..., description="Application timestamp in ISO 8601")
    profile_result: dict[str, Any] = Field(default_factory=dict)
    risk_result: dict[str, Any] = Field(default_factory=dict)


class ReviewActionOutput(BaseModel):
    """Output schema for review-action orchestration."""

    action_taken: str
    notification_status: str
    review_queue: str | None
    manual_review_owner: str | None
    reviewer_role: str | None
    review_due_timestamp: str | None
    review_status: str
    status_transition: str
    transition_history: list[dict[str, str]]


def _review_rules() -> dict[str, Any]:
    cfg = settings.loan_rules.get("review_action", {})
    return cfg if isinstance(cfg, dict) else {}


def _default_non_review_output() -> dict[str, Any]:
    return {
        "action_taken": "NO_ACTION_REQUIRED",
        "notification_status": "NOT_SENT",
        "review_queue": None,
        "manual_review_owner": None,
        "reviewer_role": None,
        "review_due_timestamp": None,
        "review_status": "NOT_REQUIRED",
        "status_transition": "NONE",
        "transition_history": [],
    }


def _derive_review_queue(risk_score: float, loan_amount: float, rules: dict[str, Any]) -> str:
    queue_rules = rules.get("queue_rules", {})

    high_value_threshold = float(queue_rules.get("high_value_threshold", 2500000.0))
    medium_risk_min = float(queue_rules.get("medium_risk_min", 40.0))
    high_risk_min = float(queue_rules.get("high_risk_min", 70.0))

    if loan_amount >= high_value_threshold:
        return str(queue_rules.get("high_value_queue", "UNDERWRITING_HIGH_VALUE"))
    if risk_score >= high_risk_min:
        return str(queue_rules.get("high_risk_queue", "UNDERWRITING_HIGH_RISK"))
    if risk_score >= medium_risk_min:
        return str(queue_rules.get("medium_risk_queue", "UNDERWRITING_MEDIUM_RISK"))
    return str(queue_rules.get("default_queue", "UNDERWRITING_GENERAL"))


def _due_timestamp(base_ts: datetime, queue: str, rules: dict[str, Any]) -> str:
    sla_map = rules.get("sla_hours_by_queue", {})
    default_hours = float(rules.get("default_sla_hours", 48))
    hours = float(sla_map.get(queue, default_hours))
    return (base_ts + timedelta(hours=hours)).isoformat()


def orchestrate_review_action(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Assign review workflow actions for a decision outcome.

    REVIEW_REQUIRED receives queue, reviewer-role, owner placeholder,
    and SLA timestamp. Other verdicts receive no-op action metadata.
    """
    validated = ReviewActionInput(**payload)

    if validated.verdict != "REVIEW_REQUIRED":
        return ReviewActionOutput(**_default_non_review_output()).model_dump()

    rules = _review_rules()
    risk_score = float((validated.risk_result or {}).get("risk_score", 50.0))
    queue = _derive_review_queue(risk_score, validated.loan_amount, rules)

    reviewer_role_by_queue = rules.get("reviewer_role_by_queue", {})
    reviewer_role = str(reviewer_role_by_queue.get(queue, rules.get("default_reviewer_role", "UNDERWRITER_L2")))
    owner = str(rules.get("default_owner", "unassigned"))

    now_utc = datetime.now(timezone.utc)
    due_ts = _due_timestamp(now_utc, queue, rules)

    output = {
        "action_taken": "MANUAL_REVIEW_INITIATED",
        "notification_status": "SENT_DISPLAY",
        "review_queue": queue,
        "manual_review_owner": owner,
        "reviewer_role": reviewer_role,
        "review_due_timestamp": due_ts,
        "review_status": "QUEUED",
        "status_transition": "REVIEW_REQUIRED_CREATED_TO_QUEUED",
        "transition_history": [
            {
                "from": "REVIEW_REQUIRED_CREATED",
                "to": "QUEUED",
                "at": now_utc.isoformat(),
                "reason": "Auto-routed by review_action rules",
            }
        ],
    }

    log.info(
        "review_action_orchestrated",
        applicant_id=validated.applicant_id,
        review_queue=queue,
        review_due_timestamp=due_ts,
    )

    return ReviewActionOutput(**output).model_dump()
