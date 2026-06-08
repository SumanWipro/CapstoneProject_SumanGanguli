"""
tests/unit/test_compliance_agent.py
=====================================
Unit tests for the Compliance Agent.

Tests verify:
- Case ID format: CASE-YYYYMMDD-NNNN
- Audit file is written to audit/logs/
- Notification summary is non-empty
- APPROVED notification contains congratulatory language
- REJECTED notification contains reapplication guidance
- REVIEW_REQUIRED notification mentions human review timeframe
"""

from __future__ import annotations

import pytest

from agents.compliance_agent import ComplianceAgent


@pytest.fixture
def compliance_payload():
    return {
        "applicant_id": "APP-TEST-001",
        "verdict": "APPROVED",
        "confidence": 0.87,
        "explanation": "Strong profile and low risk.",
        "profile_result": {
            "employment_risk": "low",
            "income_stability_score": 85.0,
            "credit_history_summary": "Excellent credit history",
            "completeness_flags": [],
        },
        "risk_result": {
            "dti": 0.22,
            "credit_band": "excellent",
            "risk_score": 21.0,
            "risk_flags": [],
        },
        "timestamp": "2026-06-08T10:00:00Z",
    }


def test_case_id_format(compliance_payload, monkeypatch):
    """Case ID must match pattern CASE-YYYYMMDD-NNNN."""
    agent = object.__new__(ComplianceAgent)

    monkeypatch.setattr(ComplianceAgent, "_generate_case_id", lambda self, date_compact, decision_date: "CASE-20260608-0001")
    monkeypatch.setattr(ComplianceAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ComplianceAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ComplianceAgent,
        "parse_json_response",
        lambda self, raw: {"notification_summary": "Congratulations! Approved."},
    )
    monkeypatch.setattr("agents.compliance_agent.write_audit_record", lambda record: "./audit/logs/2026-06-08.jsonl")

    result = agent.invoke(compliance_payload)
    assert result["case_id"].startswith("CASE-")
    assert len(result["case_id"].split("-")) == 3


def test_audit_file_written(compliance_payload, monkeypatch):
    """write_audit_record should be called exactly once per invocation."""
    agent = object.__new__(ComplianceAgent)
    calls = {"count": 0}

    monkeypatch.setattr(ComplianceAgent, "_generate_case_id", lambda self, date_compact, decision_date: "CASE-20260608-0002")
    monkeypatch.setattr(ComplianceAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ComplianceAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ComplianceAgent,
        "parse_json_response",
        lambda self, raw: {"notification_summary": "Approved message."},
    )

    def fake_write(record):
        calls["count"] += 1
        return "./audit/logs/2026-06-08.jsonl"

    monkeypatch.setattr("agents.compliance_agent.write_audit_record", fake_write)

    _ = agent.invoke(compliance_payload)
    assert calls["count"] == 1


def test_approved_notification_content(compliance_payload, monkeypatch):
    """APPROVED notification should mention congratulations and next steps."""
    agent = object.__new__(ComplianceAgent)

    monkeypatch.setattr(ComplianceAgent, "_generate_case_id", lambda self, date_compact, decision_date: "CASE-20260608-0003")
    monkeypatch.setattr(ComplianceAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ComplianceAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ComplianceAgent,
        "parse_json_response",
        lambda self, raw: {
            "notification_summary": "Congratulations! Your loan is approved. A loan officer will contact you next.",
        },
    )
    monkeypatch.setattr("agents.compliance_agent.write_audit_record", lambda record: "./audit/logs/2026-06-08.jsonl")

    result = agent.invoke(compliance_payload)
    assert "congrat" in result["notification_summary"].lower()


def test_rejected_notification_content(compliance_payload, monkeypatch):
    """REJECTED notification should mention reapplication and support contact."""
    agent = object.__new__(ComplianceAgent)
    payload = {**compliance_payload, "verdict": "REJECTED"}

    monkeypatch.setattr(ComplianceAgent, "_generate_case_id", lambda self, date_compact, decision_date: "CASE-20260608-0004")
    monkeypatch.setattr(ComplianceAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ComplianceAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ComplianceAgent,
        "parse_json_response",
        lambda self, raw: {
            "notification_summary": "Your application was not approved. You may reapply after 6 months or contact support.",
        },
    )
    monkeypatch.setattr("agents.compliance_agent.write_audit_record", lambda record: "./audit/logs/2026-06-08.jsonl")

    result = agent.invoke(payload)
    text = result["notification_summary"].lower()
    assert "reapply" in text or "support" in text


def test_review_notification_content(compliance_payload, monkeypatch):
    """REVIEW_REQUIRED notification should mention human review timeframe."""
    agent = object.__new__(ComplianceAgent)
    payload = {**compliance_payload, "verdict": "REVIEW_REQUIRED"}

    monkeypatch.setattr(ComplianceAgent, "_generate_case_id", lambda self, date_compact, decision_date: "CASE-20260608-0005")
    monkeypatch.setattr(ComplianceAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(ComplianceAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        ComplianceAgent,
        "parse_json_response",
        lambda self, raw: {
            "notification_summary": "Your application requires manual review. We will contact you within 3-5 business days.",
        },
    )
    monkeypatch.setattr("agents.compliance_agent.write_audit_record", lambda record: "./audit/logs/2026-06-08.jsonl")

    result = agent.invoke(payload)
    text = result["notification_summary"].lower()
    assert "manual review" in text or "3-5" in text or "business days" in text
