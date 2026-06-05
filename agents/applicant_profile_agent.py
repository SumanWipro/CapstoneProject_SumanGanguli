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
                valid (bool)             — True if all checks pass
                flags (list[str])        — issue codes, empty if none
                employment_band (str)    — stable | moderate | unstable
                age_eligible (bool)      — True if age in [18, 70]
                income_consistent (bool) — True if income plausible for type

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

        result: ProfileResult = {
            "valid":              bool(parsed.get("valid", False)),
            "flags":              list(parsed.get("flags", [])),
            "employment_band":    str(parsed.get("employment_band", "unstable")),
            "age_eligible":       bool(parsed.get("age_eligible", False)),
            "income_consistent":  bool(parsed.get("income_consistent", False)),
        }

        log.info(
            "applicant_profile_agent_complete",
            applicant_id=applicant_id,
            valid=result["valid"],
            employment_band=result["employment_band"],
            flags=result["flags"],
        )
        return result
