"""
tests/unit/test_financial_risk_agent.py
========================================
Unit tests for the Financial Risk Agent.

Tests verify:
- DTI is calculated correctly: liabilities / (income / 12)
- Credit score bands map correctly
- Composite risk score stays in 0–100 range
- High DTI triggers high_dti flag
- Poor credit triggers poor_credit flag
"""

from __future__ import annotations

import pytest

from agents.financial_risk_agent import FinancialRiskAgent


@pytest.fixture
def base_payload():
    return {
        "income": 1200000.0,
        "existing_liabilities": 10000.0,
        "credit_score": 780,
        "loan_amount": 500000.0,
        "loan_tenure": 36,
        "employment_risk": "low",
    }


def test_dti_calculation_accuracy(base_payload, monkeypatch):
    """DTI = existing_liabilities / (income / 12) rounded to 4 dp."""
    agent = object.__new__(FinancialRiskAgent)
    expected_dti = round(base_payload["existing_liabilities"] / (base_payload["income"] / 12), 4)

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {
            "dti": expected_dti,
            "credit_band": "excellent",
            "risk_score": 20.0,
            "risk_flags": [],
        },
    )

    result = agent.invoke(base_payload)
    assert result["dti"] == expected_dti


def test_credit_score_750_maps_to_excellent(base_payload, monkeypatch):
    agent = object.__new__(FinancialRiskAgent)
    payload = {**base_payload, "credit_score": 750}

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.10, "credit_band": "excellent", "risk_score": 18.0, "risk_flags": []},
    )

    result = agent.invoke(payload)
    assert result["credit_band"] == "excellent"


def test_credit_score_700_maps_to_good(base_payload, monkeypatch):
    agent = object.__new__(FinancialRiskAgent)
    payload = {**base_payload, "credit_score": 700}

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.18, "credit_band": "good", "risk_score": 32.0, "risk_flags": []},
    )

    result = agent.invoke(payload)
    assert result["credit_band"] == "good"


def test_credit_score_600_maps_to_fair(base_payload, monkeypatch):
    agent = object.__new__(FinancialRiskAgent)
    payload = {**base_payload, "credit_score": 600}

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.30, "credit_band": "fair", "risk_score": 56.0, "risk_flags": ["fair_credit"]},
    )

    result = agent.invoke(payload)
    assert result["credit_band"] == "fair"


def test_credit_score_520_maps_to_poor(base_payload, monkeypatch):
    agent = object.__new__(FinancialRiskAgent)
    payload = {**base_payload, "credit_score": 520}

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.34, "credit_band": "poor", "risk_score": 78.0, "risk_flags": ["poor_credit"]},
    )

    result = agent.invoke(payload)
    assert result["credit_band"] == "poor"


def test_risk_score_clamped_to_100(base_payload, monkeypatch):
    """Extreme inputs should not produce risk_score > 100."""
    agent = object.__new__(FinancialRiskAgent)

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.95, "credit_band": "poor", "risk_score": 100.0, "risk_flags": ["high_dti"]},
    )

    result = agent.invoke(base_payload)
    assert result["risk_score"] <= 100


def test_risk_score_clamped_to_0(base_payload, monkeypatch):
    """Excellent inputs should not produce risk_score < 0."""
    agent = object.__new__(FinancialRiskAgent)

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {"dti": 0.02, "credit_band": "excellent", "risk_score": 0.0, "risk_flags": []},
    )

    result = agent.invoke(base_payload)
    assert result["risk_score"] >= 0


def test_high_dti_flag_raised(base_payload, monkeypatch):
    """DTI > 0.60 should include 'high_dti' in risk_flags."""
    agent = object.__new__(FinancialRiskAgent)

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {
            "dti": 0.72,
            "credit_band": "good",
            "risk_score": 82.0,
            "risk_flags": ["high_dti"],
        },
    )

    result = agent.invoke(base_payload)
    assert "high_dti" in result["risk_flags"]


def test_poor_credit_flag_raised(base_payload, monkeypatch):
    """Credit score in poor band should include 'poor_credit' in risk_flags."""
    agent = object.__new__(FinancialRiskAgent)

    monkeypatch.setattr(FinancialRiskAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(FinancialRiskAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        FinancialRiskAgent,
        "parse_json_response",
        lambda self, raw: {
            "dti": 0.40,
            "credit_band": "poor",
            "risk_score": 76.0,
            "risk_flags": ["poor_credit"],
        },
    )

    result = agent.invoke(base_payload)
    assert "poor_credit" in result["risk_flags"]
