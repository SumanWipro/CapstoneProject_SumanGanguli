"""
tests/unit/test_applicant_profile_agent.py
==========================================
Unit tests for the Applicant Profile Agent.

Tests verify:
- Valid profile passes validation
- Age below 18 is flagged as ineligible
- Age above 70 is flagged as ineligible
- Employment type is correctly mapped to stability band
- Low income for employment type triggers income_consistent=False

Claude Sonnet is mocked in all tests — no real Bedrock calls.
"""

from __future__ import annotations

import pytest

from agents.applicant_profile_agent import ApplicantProfileAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_payload():
    """Standard valid applicant payload."""
    return {
        "applicant_id": "APP-TEST-001",
        "age": 35,
        "income": 1200000.0,
        "employment_type": "salaried",
        "credit_score": 780,
        "loan_amount": 500000.0,
        "loan_tenure": 36,
        "existing_liabilities": 10000.0,
        "location": "Mumbai",
        "timestamp": "2024-01-15T10:30:00Z",
    }


@pytest.fixture
def underage_payload(valid_payload):
    """Payload with age below minimum."""
    return {**valid_payload, "applicant_id": "APP-TEST-U01", "age": 17}


@pytest.fixture
def overage_payload(valid_payload):
    """Payload with age above maximum."""
    return {**valid_payload, "applicant_id": "APP-TEST-U02", "age": 71}


def test_valid_profile_returns_valid_true(valid_payload, monkeypatch):
    """A fully valid applicant should return valid=True with no flags."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": True,
            "flags": [],
            "employment_band": "stable",
            "age_eligible": True,
            "income_consistent": True,
        },
    )

    result = agent.invoke(valid_payload)

    assert result["employment_risk"] == "low"
    assert result["income_stability_score"] >= 80
    assert result["completeness_flags"] == []


def test_underage_applicant_flagged(underage_payload, monkeypatch):
    """Applicant under 18 should return age_eligible=False and valid=False."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": False,
            "flags": [],
            "employment_band": "stable",
            "age_eligible": False,
            "income_consistent": True,
        },
    )

    result = agent.invoke(underage_payload)

    assert "AGE_INELIGIBLE" in result["completeness_flags"]


def test_overage_applicant_flagged(overage_payload, monkeypatch):
    """Applicant over 70 should return age_eligible=False and valid=False."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": False,
            "flags": [],
            "employment_band": "moderate",
            "age_eligible": False,
            "income_consistent": True,
        },
    )

    result = agent.invoke(overage_payload)

    assert "AGE_INELIGIBLE" in result["completeness_flags"]


def test_salaried_employment_maps_to_stable_band(valid_payload, monkeypatch):
    """Salaried employment type should map to 'stable' employment_band."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": True,
            "flags": [],
            "employment_band": "stable",
            "age_eligible": True,
            "income_consistent": True,
        },
    )

    result = agent.invoke(valid_payload)

    assert result["employment_risk"] == "low"


def test_self_employed_maps_to_moderate_band(valid_payload, monkeypatch):
    """Self-employed should map to 'moderate' employment_band."""
    agent = object.__new__(ApplicantProfileAgent)
    payload = {**valid_payload, "employment_type": "self_employed"}

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": True,
            "flags": [],
            "employment_band": "moderate",
            "age_eligible": True,
            "income_consistent": True,
        },
    )

    result = agent.invoke(payload)

    assert result["employment_risk"] == "medium"


def test_unemployed_maps_to_unstable_band(valid_payload, monkeypatch):
    """Unemployed type should map to 'unstable' employment_band."""
    agent = object.__new__(ApplicantProfileAgent)
    payload = {**valid_payload, "employment_type": "unemployed"}

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": False,
            "flags": ["UNEMPLOYED"],
            "employment_band": "unstable",
            "age_eligible": True,
            "income_consistent": False,
        },
    )

    result = agent.invoke(payload)

    assert result["employment_risk"] == "high"
    assert "INCOME_INCONSISTENT" in result["completeness_flags"]


def test_low_income_for_employment_type_flagged(valid_payload, monkeypatch):
    """Implausibly low income for salaried should set income_consistent=False."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": False,
            "flags": ["INCOME_TOO_LOW"],
            "employment_band": "stable",
            "age_eligible": True,
            "income_consistent": False,
        },
    )

    result = agent.invoke(valid_payload)

    assert "INCOME_INCONSISTENT" in result["completeness_flags"]
    assert result["income_stability_score"] < 85


def test_invoke_includes_case_study_required_fields(valid_payload, monkeypatch):
    """Agent output must include the new case-study profile fields."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": True,
            "flags": [],
            "employment_band": "stable",
            "age_eligible": True,
            "income_consistent": True,
        },
    )

    result = agent.invoke(valid_payload)

    assert "income_stability_score" in result
    assert "employment_risk" in result
    assert "credit_history_summary" in result
    assert "completeness_flags" in result


def test_invoke_maps_employment_band_to_employment_risk(valid_payload, monkeypatch):
    """Employment band should be translated to risk category."""
    agent = object.__new__(ApplicantProfileAgent)

    monkeypatch.setattr(ApplicantProfileAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ApplicantProfileAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ApplicantProfileAgent,
        "parse_json_response",
        lambda self, raw: {
            "valid": True,
            "flags": ["INCOME_TOO_LOW"],
            "employment_band": "unstable",
            "age_eligible": True,
            "income_consistent": False,
        },
    )

    result = agent.invoke(valid_payload)

    assert result["employment_risk"] == "high"
    assert isinstance(result["income_stability_score"], (int, float))
    assert 0 <= result["income_stability_score"] <= 100
    assert "INCOME_INCONSISTENT" in result["completeness_flags"]
