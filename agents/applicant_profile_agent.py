"""
agents/applicant_profile_agent.py
==================================
Applicant Profile Agent — Agent 1 of 5.

Agent Responsibility:
- Validate all 10 required input fields are present and correctly typed
- Verify applicant age is within eligibility range (18–70)
- Map employment_type to a stability band (stable / moderate / unstable)
- Flag income inconsistencies against employment-type income floors
- Return a structured ProfileResult dict

This agent does NOT calculate risk scores or look up policies.
Those responsibilities belong to FinancialRiskAgent and PolicyKnowledgeAgent.

Prompt file: prompts/applicant_profile.txt
Returns:     orchestrator.state.ProfileResult TypedDict
"""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import BaseAgent
from orchestrator.state import ProfileResult
from utils.logger import get_logger

log = get_logger(__name__, component="applicant_profile_agent")


class ApplicantProfileAgent(BaseAgent):
    """
    Validates applicant profile data using Claude Sonnet via AWS Bedrock.

    Inherits build_prompt(), call_claude(), parse_json_response() from BaseAgent.
    """

    prompt_file = "applicant_profile.txt"

    def invoke(self, payload: dict[str, Any]) -> ProfileResult:
        """
        Validate applicant profile and return a ProfileResult.

        Execution steps:
            1. Extract all 10 applicant fields from payload
            2. Render the applicant_profile.txt prompt template
            3. Call Claude Sonnet via Bedrock with retry
            4. Parse the JSON response into a ProfileResult dict

        Args:
            payload: Dict with all 10 applicant fields:
                applicant_id, age, income, employment_type, credit_score,
                loan_amount, loan_tenure, existing_liabilities, location,
                timestamp

        Returns:
            ProfileResult TypedDict:
                income_stability_score (float) — normalized profile stability score (0-100)
                employment_risk (str)          — low | medium | high
                credit_history_summary (str)   — human-readable credit summary
                completeness_flags (list[str]) — completeness/validation flags

        Raises:
            json.JSONDecodeError: If Claude returns malformed JSON.
            ClientError:          If Bedrock call fails after 3 retries.
        """
        applicant_id = payload.get("applicant_id", "UNKNOWN")
        log.info("applicant_profile_agent_invoked", applicant_id=applicant_id)

        # Step 1: Build prompt — all 10 fields injected into template
        prompt = self.build_prompt(
            applicant_id        = str(payload.get("applicant_id", "")),
            age                 = str(payload.get("age", "")),
            income              = str(payload.get("income", "")),
            employment_type     = str(payload.get("employment_type", "")),
            credit_score        = str(payload.get("credit_score", "")),
            loan_amount         = str(payload.get("loan_amount", "")),
            loan_tenure         = str(payload.get("loan_tenure", "")),
            existing_liabilities= str(payload.get("existing_liabilities", "")),
            location            = str(payload.get("location", "")),
            timestamp           = str(payload.get("timestamp", "")),
        )

        # Step 2: Call Claude Sonnet
        raw = self.call_claude(prompt)

        # Step 3: Parse structured JSON response
        parsed = self.parse_json_response(raw)

        employment_band = str(parsed.get("employment_band", "unstable"))
        income_consistent = bool(parsed.get("income_consistent", False))
        flags = list(parsed.get("flags", []))

        # Case-study alignment fields
        employment_risk_map = {
            "stable": "low",
            "moderate": "medium",
            "unstable": "high",
        }
        employment_risk = employment_risk_map.get(employment_band, "high")

        base_stability_score = {
            "stable": 85,
            "moderate": 65,
            "unstable": 40,
        }.get(employment_band, 40)
        income_stability_score = max(0, min(100, base_stability_score if income_consistent else base_stability_score - 25))

        credit_score = int(payload.get("credit_score", 0) or 0)
        if credit_score >= 750:
            credit_history_summary = f"Excellent credit history ({credit_score})"
        elif credit_score >= 650:
            credit_history_summary = f"Good credit history ({credit_score})"
        elif credit_score >= 550:
            credit_history_summary = f"Fair credit history ({credit_score})"
        else:
            credit_history_summary = f"Poor credit history ({credit_score})"

        completeness_flags = list(flags)
        if not bool(parsed.get("age_eligible", False)) and "AGE_INELIGIBLE" not in completeness_flags:
            completeness_flags.append("AGE_INELIGIBLE")
        if not income_consistent and "INCOME_INCONSISTENT" not in completeness_flags:
            completeness_flags.append("INCOME_INCONSISTENT")

        result: ProfileResult = {
            "income_stability_score": float(income_stability_score),
            "employment_risk": employment_risk,
            "credit_history_summary": credit_history_summary,
            "completeness_flags": completeness_flags,
        }

        log.info(
            "applicant_profile_agent_complete",
            applicant_id=applicant_id,
            employment_risk=result["employment_risk"],
            income_stability_score=result["income_stability_score"],
            completeness_flags=result["completeness_flags"],
        )
        return result
