"""
agents/compliance_agent.py
===========================
Compliance Agent — Agent 5 of 5.

Agent Responsibility:
- Generate a unique, time-ordered Case ID (CASE-YYYYMMDD-NNNN)
- Write a fully structured audit record to audit/logs/ via utils.audit
- Use Claude Sonnet to produce an applicant-facing notification summary
- Return a structured AuditRecord dict

This agent does NOT make or modify the loan decision.
It only records, summarises, and certifies the output of LoanDecisionAgent.

Case ID generation:
    Format:  CASE-{YYYYMMDD}-{NNNN}
    Example: CASE-20240115-0042
    NNNN is derived from the count of existing records in today's audit file,
    padded to 4 digits. This is deterministic and collision-free within a
    single process (the audit file is appended atomically).

Prompt file: prompts/compliance.txt
Returns:     orchestrator.state.AuditRecord TypedDict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from orchestrator.state import AuditRecord
from utils.audit import write_audit_record, read_audit_records
from utils.logger import get_logger

log = get_logger(__name__, component="compliance_agent")


class ComplianceAgent(BaseAgent):
    """
    Handles audit trail and compliance output using Claude Sonnet.

    Inherits build_prompt(), call_claude(), parse_json_response() from BaseAgent.
    """

    prompt_file = "compliance.txt"

    def invoke(self, payload: dict[str, Any]) -> AuditRecord:
        """
        Generate Case ID, write audit log, and return AuditRecord.

        Execution steps:
            1. Derive today's UTC decision date
            2. Generate a unique Case ID from date + existing record count
            3. Build the compliance.txt notification prompt
            4. Call Claude Sonnet to generate applicant notification text
            5. Parse the JSON response
            6. Assemble the full audit record dict
            7. Write the record to audit/logs/ via utils.audit
            8. Return the AuditRecord

        Args:
            payload: Dict with full case data:
                applicant_id   (str)
                verdict        (str)   — APPROVED | REJECTED | REVIEW_REQUIRED
                confidence     (float) — 0.0–1.0
                explanation    (str)
                profile_result (dict)
                risk_result    (dict)
                timestamp      (str)   — original application submission timestamp

        Returns:
            AuditRecord TypedDict:
                case_id              (str) — CASE-YYYYMMDD-NNNN
                log_path             (str) — path to the audit file written
                notification_summary (str) — applicant-facing notification

        Raises:
            json.JSONDecodeError: If Claude returns malformed JSON.
            ClientError:          If Bedrock call fails after 3 retries.
            OSError:              If the audit log directory cannot be written.
        """
        applicant_id = payload.get("applicant_id", "UNKNOWN")
        verdict      = str(payload.get("verdict", "REVIEW_REQUIRED"))
        confidence   = float(payload.get("confidence", 0.5))
        explanation  = str(payload.get("explanation", ""))

        log.info(
            "compliance_agent_invoked",
            applicant_id=applicant_id,
            verdict=verdict,
        )

        # Step 1: UTC decision date
        now           = datetime.now(timezone.utc)
        decision_date = now.strftime("%Y-%m-%d")
        date_compact  = now.strftime("%Y%m%d")

        # Step 2: Generate Case ID
        case_id = self._generate_case_id(date_compact, decision_date)

        # Step 3: Build notification prompt
        prompt = self.build_prompt(
            applicant_id  = str(applicant_id),
            verdict       = verdict,
            confidence    = f"{confidence:.2f}",
            decision_date = decision_date,
            case_id       = case_id,
            explanation   = explanation,
        )

        # Step 4 & 5: Call Claude and parse notification
        raw    = self.call_claude(prompt)
        parsed = self.parse_json_response(raw)
        notification_summary = str(parsed.get("notification_summary", ""))

        # Step 6: Assemble full audit record
        risk_result    = payload.get("risk_result", {})
        profile_result = payload.get("profile_result", {})

        audit_dict = {
            "case_id":              case_id,
            "applicant_id":         applicant_id,
            "verdict":              verdict,
            "confidence_score":     confidence,
            "explanation":          explanation,
            "notification_summary": notification_summary,
            "action_taken":         payload.get("action_taken", "NO_ACTION_REQUIRED"),
            "notification_status":  payload.get("notification_status", "NOT_SENT"),
            "review_queue":         payload.get("review_queue"),
            "manual_review_owner":  payload.get("manual_review_owner"),
            "reviewer_role":        payload.get("reviewer_role"),
            "review_due_timestamp": payload.get("review_due_timestamp"),
            "review_status":        payload.get("review_status", "NOT_REQUIRED"),
            "status_transition":    payload.get("status_transition", "NONE"),
            "transition_history":   payload.get("transition_history", []),
            "decision_date":        decision_date,
            "application_timestamp":payload.get("timestamp", ""),
            # Risk metrics (for dashboard analytics)
            "dti":                  risk_result.get("dti"),
            "credit_band":          risk_result.get("credit_band"),
            "risk_score":           risk_result.get("risk_score"),
            "risk_flags":           risk_result.get("risk_flags", []),
            # Profile metrics
            "employment_risk":      profile_result.get("employment_risk"),
            "income_stability_score": profile_result.get("income_stability_score"),
            "credit_history_summary": profile_result.get("credit_history_summary"),
            "completeness_flags":   profile_result.get("completeness_flags", []),
        }

        # Step 7: Write to audit/logs/
        log_path = write_audit_record(audit_dict)

        result: AuditRecord = {
            "case_id":              case_id,
            "log_path":             str(log_path),
            "notification_summary": notification_summary,
        }

        log.info(
            "compliance_agent_complete",
            applicant_id=applicant_id,
            case_id=case_id,
            log_path=str(log_path),
        )
        return result

    # ------------------------------------------------------------------
    # Private: Case ID generator
    # ------------------------------------------------------------------

    def _generate_case_id(self, date_compact: str, decision_date: str) -> str:
        """
        Generate a unique Case ID for today's decision.

        Format: CASE-{YYYYMMDD}-{NNNN}
        NNNN = (number of records already in today's audit file) + 1,
        zero-padded to 4 digits. This is deterministic within a process
        and collision-free because utils.audit.write_audit_record() appends
        atomically.

        Args:
            date_compact:  Date string YYYYMMDD (for the ID body)
            decision_date: Date string YYYY-MM-DD (for reading today's file)

        Returns:
            Case ID string e.g. "CASE-20240115-0042"
        """
        existing = read_audit_records(decision_date)
        sequence = len(existing) + 1
        case_id  = f"CASE-{date_compact}-{sequence:04d}"
        log.debug("case_id_generated", case_id=case_id, sequence=sequence)
        return case_id
