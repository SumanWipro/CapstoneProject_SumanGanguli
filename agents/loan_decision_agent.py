"""
agents/loan_decision_agent.py
==============================
Loan Decision Agent — Agent 4 of 5.

Agent Responsibility:
- Synthesise ProfileResult + RiskResult + PolicyChunks into a final verdict
- Classify the application as APPROVED, REJECTED, or REVIEW_REQUIRED
- Generate a confidence score (0.0–1.0) for the decision
- Produce a plain-English explanation referencing specific financial metrics
- Return a structured DecisionResult dict

This agent does NOT write audit records or generate Case IDs.
Those responsibilities belong exclusively to the ComplianceAgent.

Prompt file: prompts/loan_decision.txt
Returns:     orchestrator.state.DecisionResult TypedDict
"""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import BaseAgent
from orchestrator.state import DecisionResult
from utils.logger import get_logger

log = get_logger(__name__, component="loan_decision_agent")


class LoanDecisionAgent(BaseAgent):
    """
    Generates the final loan verdict using Claude Sonnet via AWS Bedrock.

    Inherits build_prompt(), call_claude(), parse_json_response() from BaseAgent.
    """

    prompt_file = "loan_decision.txt"

    def invoke(self, payload: dict[str, Any]) -> DecisionResult:
        """
        Synthesise all prior agent results and return a DecisionResult.

        Execution steps:
            1. Serialise ProfileResult and RiskResult to readable strings
            2. Extract policy_summary from PolicyChunks
            3. Render the loan_decision.txt prompt template with full context
            4. Call Claude Sonnet via Bedrock with retry
            5. Parse the JSON response into a DecisionResult dict

        Args:
            payload: Dict with synthesised context:
                applicant_id   (str)   — for logging
                loan_amount    (float) — from original request
                loan_tenure    (int)   — from original request
                profile_result (dict)  — ProfileResult from Agent 1
                risk_result    (dict)  — RiskResult from Agent 2
                policy_summary (str)   — policy_summary from Agent 3 PolicyChunks

        Returns:
            DecisionResult TypedDict:
                verdict (str)       — APPROVED | REJECTED | REVIEW_REQUIRED
                confidence (float)  — 0.0–1.0
                explanation (str)   — plain-English rationale (2–4 sentences)

        Raises:
            json.JSONDecodeError: If Claude returns malformed JSON.
            ClientError:          If Bedrock call fails after 3 retries.
        """
        applicant_id   = payload.get("applicant_id", "UNKNOWN")
        profile_result = payload.get("profile_result", {})
        risk_result    = payload.get("risk_result", {})
        policy_summary = payload.get("policy_summary", "No policy context available.")

        log.info(
            "loan_decision_agent_invoked",
            applicant_id=applicant_id,
            risk_score=risk_result.get("risk_score"),
            credit_band=risk_result.get("credit_band"),
        )

        # Step 1: Serialise sub-results as readable JSON strings for the prompt
        profile_str = json.dumps(profile_result, indent=2)
        risk_str    = json.dumps(risk_result, indent=2)

        # Step 2: Build prompt with full synthesised context
        prompt = self.build_prompt(
            applicant_id   = str(applicant_id),
            loan_amount    = str(payload.get("loan_amount", 0)),
            loan_tenure    = str(payload.get("loan_tenure", 12)),
            profile_result = profile_str,
            risk_result    = risk_str,
            policy_summary = policy_summary,
        )

        # Step 3: Call Claude Sonnet
        raw = self.call_claude(prompt)

        # Step 4: Parse structured JSON response
        parsed = self.parse_json_response(raw)

        # Validate and clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))

        result: DecisionResult = {
            "verdict":     str(parsed.get("verdict", "REVIEW_REQUIRED")),
            "confidence":  confidence,
            "explanation": str(parsed.get("explanation", "")),
        }

        log.info(
            "loan_decision_agent_complete",
            applicant_id=applicant_id,
            verdict=result["verdict"],
            confidence=result["confidence"],
        )
        return result
