"""
agents/financial_risk_agent.py
================================
Financial Risk Agent — Agent 2 of 5.

Agent Responsibility:
- Calculate DTI ratio: existing_liabilities / (income / 12)
- Map CIBIL credit score to a risk band (excellent / good / fair / poor)
- Compute a composite risk score (0–100) combining DTI, credit band,
  and employment stability band
- Identify active risk flags (high_dti, poor_credit, unstable_employment,
  high_loan_to_income, thin_credit_file)
- Return a structured RiskResult dict

This agent does NOT make the final loan decision or look up policies.
Those responsibilities belong to LoanDecisionAgent and PolicyKnowledgeAgent.

Prompt file: prompts/financial_risk.txt
Returns:     orchestrator.state.RiskResult TypedDict
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from orchestrator.state import RiskResult
from utils.logger import get_logger

log = get_logger(__name__, component="financial_risk_agent")


class FinancialRiskAgent(BaseAgent):
    """
    Computes financial risk metrics using Claude Sonnet via AWS Bedrock.

    Inherits build_prompt(), call_claude(), parse_json_response() from BaseAgent.
    """

    prompt_file = "financial_risk.txt"

    def invoke(self, payload: dict[str, Any]) -> RiskResult:
        """
        Calculate financial risk and return a RiskResult.

        Execution steps:
            1. Extract financial fields and employment_band from payload
            2. Render the financial_risk.txt prompt template
            3. Call Claude Sonnet via Bedrock with retry
            4. Parse the JSON response into a RiskResult dict

        Args:
            payload: Dict with financial fields:
                income (float)                — annual gross income in INR
                existing_liabilities (float)  — monthly debt obligations in INR
                credit_score (int)            — CIBIL score 300–900
                loan_amount (float)           — requested loan principal in INR
                loan_tenure (int)             — repayment period in months
                employment_band (str)         — from ProfileResult

        Returns:
            RiskResult TypedDict:
                dti (float)          — debt-to-income ratio (4 dp)
                credit_band (str)    — excellent | good | fair | poor
                risk_score (float)   — composite 0–100
                risk_flags (list)    — active flag codes, empty if none

        Raises:
            json.JSONDecodeError: If Claude returns malformed JSON.
            ClientError:          If Bedrock call fails after 3 retries.
        """
        log.info(
            "financial_risk_agent_invoked",
            income=payload.get("income"),
            credit_score=payload.get("credit_score"),
        )

        # Step 1: Build prompt
        prompt = self.build_prompt(
            income               = str(payload.get("income", 0)),
            existing_liabilities = str(payload.get("existing_liabilities", 0)),
            credit_score         = str(payload.get("credit_score", 300)),
            loan_amount          = str(payload.get("loan_amount", 0)),
            loan_tenure          = str(payload.get("loan_tenure", 12)),
            employment_band      = str(payload.get("employment_band", "stable")),
        )

        # Step 2: Call Claude Sonnet
        raw = self.call_claude(prompt)

        # Step 3: Parse structured JSON response
        parsed = self.parse_json_response(raw)

        result: RiskResult = {
            "dti":         float(parsed.get("dti", 0.0)),
            "credit_band": str(parsed.get("credit_band", "poor")),
            "risk_score":  float(parsed.get("risk_score", 100.0)),
            "risk_flags":  list(parsed.get("risk_flags", [])),
        }

        log.info(
            "financial_risk_agent_complete",
            dti=result["dti"],
            credit_band=result["credit_band"],
            risk_score=result["risk_score"],
            risk_flags=result["risk_flags"],
        )
        return result
