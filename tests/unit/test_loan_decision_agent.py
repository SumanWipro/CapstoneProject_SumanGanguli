"""
tests/unit/test_loan_decision_agent.py
=======================================
Unit tests for the Loan Decision Agent.

Tests verify all three verdict paths with known inputs:
- Strong profile → APPROVED with high confidence
- Failed hard rule → REJECTED
- Borderline profile → REVIEW_REQUIRED with mid confidence
- Confidence score always in [0.0, 1.0]
- Explanation is non-empty string
"""

from __future__ import annotations

import pytest

from agents.loan_decision_agent import LoanDecisionAgent


@pytest.fixture
def decision_payload():
    return {
        "applicant_id": "APP-TEST-DEC-001",
        "loan_amount": 500000.0,
        "loan_tenure": 36,
        "profile_result": {
            "income_stability_score": 85.0,
            "employment_risk": "low",
            "credit_history_summary": "Good credit history",
            "completeness_flags": [],
        },
        "risk_result": {
            "dti": 0.22,
            "credit_band": "excellent",
            "risk_score": 22.0,
            "risk_flags": [],
        },
        "policy_summary": "All policy criteria are satisfied.",
    }


def test_excellent_profile_returns_approved(decision_payload, monkeypatch):
    """risk_score < 40, excellent credit, low DTI → APPROVED."""
    agent = object.__new__(LoanDecisionAgent)

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "APPROVED",
            "confidence": 0.91,
            "explanation": "Strong profile with low risk.",
        },
    )

    result = agent.invoke(decision_payload)
    assert result["verdict"] == "APPROVED"


def test_high_risk_score_returns_rejected(decision_payload, monkeypatch):
    """risk_score > 70 → REJECTED regardless of other factors."""
    agent = object.__new__(LoanDecisionAgent)
    payload = {**decision_payload, "risk_result": {**decision_payload["risk_result"], "risk_score": 82.0}}

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "REJECTED",
            "confidence": 0.88,
            "explanation": "Risk score exceeds rejection threshold.",
        },
    )

    result = agent.invoke(payload)
    assert result["verdict"] == "REJECTED"


def test_low_credit_score_returns_rejected(decision_payload, monkeypatch):
    """credit_score < 500 → REJECTED."""
    agent = object.__new__(LoanDecisionAgent)

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "REJECTED",
            "confidence": 0.92,
            "explanation": "Credit score below minimum policy threshold.",
        },
    )

    result = agent.invoke(decision_payload)
    assert result["verdict"] == "REJECTED"


def test_borderline_returns_review_required(decision_payload, monkeypatch):
    """Borderline inputs → REVIEW_REQUIRED."""
    agent = object.__new__(LoanDecisionAgent)
    payload = {**decision_payload, "risk_result": {**decision_payload["risk_result"], "risk_score": 55.0, "credit_band": "fair", "dti": 0.52}}

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "REVIEW_REQUIRED",
            "confidence": 0.63,
            "explanation": "Borderline profile requires human underwriting.",
        },
    )

    result = agent.invoke(payload)
    assert result["verdict"] == "REVIEW_REQUIRED"


def test_confidence_score_in_valid_range(decision_payload, monkeypatch):
    """confidence must be >= 0.0 and <= 1.0 for all verdicts."""
    agent = object.__new__(LoanDecisionAgent)

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "APPROVED",
            "confidence": 1.4,
            "explanation": "High confidence decision.",
        },
    )

    result = agent.invoke(decision_payload)
    assert 0.0 <= result["confidence"] <= 1.0


def test_explanation_is_non_empty_string(decision_payload, monkeypatch):
    """explanation field must be a non-empty string for all verdicts."""
    agent = object.__new__(LoanDecisionAgent)

    monkeypatch.setattr(LoanDecisionAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(LoanDecisionAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        LoanDecisionAgent,
        "parse_json_response",
        lambda self, raw: {
            "verdict": "APPROVED",
            "confidence": 0.81,
            "explanation": "Meets policy and risk criteria.",
        },
    )

    result = agent.invoke(decision_payload)
    assert isinstance(result["explanation"], str)
    assert result["explanation"].strip() != ""
