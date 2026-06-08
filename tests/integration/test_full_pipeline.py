"""
tests/integration/test_full_pipeline.py
=========================================
Integration tests for the full LangGraph pipeline.

Tests invoke the compiled graph end-to-end against all fixture scenarios.
Real agent calls are mocked — no Bedrock or ChromaDB required in CI.

Scenarios (from tests/fixtures/sample_applications.json):
- APP-TEST-001: APPROVED (excellent profile)
- APP-TEST-002: REJECTED (low credit score)
- APP-TEST-003: REJECTED (high DTI)
- APP-TEST-004: REVIEW_REQUIRED (borderline)
- APP-TEST-005: REJECTED (age ineligible)
- APP-TEST-006: APPROVED (government employee)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import nodes
from orchestrator.graph import build_graph

FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "sample_applications.json"


@pytest.fixture
def sample_applications():
    with open(FIXTURES_PATH) as f:
        return json.load(f)


class _FakeMCPClient:
    """Simple MCP stub for end-to-end graph tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        self.calls.append((tool_name, payload))

        applicant_id = payload.get("applicant_id", "")

        if tool_name == "validate_profile":
            return {
                "income_stability_score": 80.0,
                "employment_risk": "low" if payload.get("employment_type") in {"salaried", "government"} else "medium",
                "credit_history_summary": f"Credit profile ({payload.get('credit_score')})",
                "completeness_flags": [],
            }

        if tool_name == "calculate_risk":
            credit_score = int(payload.get("credit_score", 300))
            liabilities = float(payload.get("existing_liabilities", 0.0))
            income = float(payload.get("income", 1.0))
            monthly_income = max(income / 12.0, 1.0)
            dti = liabilities / monthly_income

            if credit_score < 500 or dti > 0.60:
                return {
                    "dti": round(dti, 4),
                    "credit_band": "poor" if credit_score < 550 else "fair",
                    "risk_score": 85.0,
                    "risk_flags": ["poor_credit" if credit_score < 500 else "high_dti"],
                }

            if applicant_id == "APP-TEST-004":
                return {
                    "dti": 0.52,
                    "credit_band": "fair",
                    "risk_score": 58.0,
                    "risk_flags": ["high_dti", "fair_credit"],
                }

            return {
                "dti": round(dti, 4),
                "credit_band": "excellent" if credit_score >= 750 else "good",
                "risk_score": 24.0,
                "risk_flags": [],
            }

        if tool_name == "query_policy":
            return {
                "chunks": ["Policy chunk"],
                "sources": ["risk_thresholds.txt"],
                "applicable_clauses": ["Clause A"],
                "policy_summary": "Policy context summary",
            }

        if tool_name == "generate_decision":
            risk = payload.get("risk_result", {})
            risk_score = float(risk.get("risk_score", 50.0))
            credit_band = risk.get("credit_band", "fair")
            dti = float(risk.get("dti", 0.0))

            if risk_score > 70 or credit_band == "poor" or dti > 0.60:
                return {
                    "verdict": "REJECTED",
                    "confidence": 0.90,
                    "explanation": "Risk exceeds policy thresholds.",
                }

            if 40 <= risk_score <= 70:
                return {
                    "verdict": "REVIEW_REQUIRED",
                    "confidence": 0.63,
                    "explanation": "Borderline case requires manual underwriting.",
                }

            return {
                "verdict": "APPROVED",
                "confidence": 0.87,
                "explanation": "Applicant meets credit and DTI criteria.",
            }

        if tool_name == "orchestrate_review_action":
            if payload.get("verdict") == "REVIEW_REQUIRED":
                return {
                    "action_taken": "MANUAL_REVIEW_INITIATED",
                    "notification_status": "SENT_DISPLAY",
                    "review_queue": "UNDERWRITING_MEDIUM_RISK",
                    "manual_review_owner": "unassigned",
                    "reviewer_role": "UNDERWRITER_L2",
                    "review_due_timestamp": "2026-06-10T10:15:00+00:00",
                    "review_status": "QUEUED",
                    "status_transition": "REVIEW_REQUIRED_CREATED_TO_QUEUED",
                    "transition_history": [
                        {
                            "from": "REVIEW_REQUIRED_CREATED",
                            "to": "QUEUED",
                            "at": "2026-06-08T10:15:01+00:00",
                            "reason": "Auto-routed by review_action rules",
                        }
                    ],
                }

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

        if tool_name == "create_audit":
            return {
                "case_id": f"CASE-20260608-{applicant_id[-3:] if applicant_id else '000'}",
                "log_path": "./audit/logs/2026-06-08.jsonl",
                "notification_summary": "Audit record created.",
            }

        return {}


@pytest.fixture
def graph_with_mocked_mcp(monkeypatch):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr(nodes, "get_mcp_client", lambda: fake_client)
    graph = build_graph()
    return graph, fake_client


def _scenario_input(sample_applications: list[dict], applicant_id: str) -> dict:
    for scenario in sample_applications:
        if scenario["input"]["applicant_id"] == applicant_id:
            return scenario["input"]
    raise AssertionError(f"Scenario not found for applicant_id={applicant_id}")


def test_approved_scenario_end_to_end(sample_applications, graph_with_mocked_mcp):
    """APP-TEST-001 should produce verdict=APPROVED."""
    graph, _ = graph_with_mocked_mcp
    initial_state = _scenario_input(sample_applications, "APP-TEST-001")

    final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": "it-approved"}})

    assert final_state["verdict"] == "APPROVED"
    assert final_state.get("case_id")
    assert final_state.get("review_status") == "NOT_REQUIRED"


def test_rejected_low_credit_end_to_end(sample_applications, graph_with_mocked_mcp):
    """APP-TEST-002 should produce verdict=REJECTED."""
    graph, _ = graph_with_mocked_mcp
    initial_state = _scenario_input(sample_applications, "APP-TEST-002")

    final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": "it-rejected-low-credit"}})

    assert final_state["verdict"] == "REJECTED"
    assert final_state.get("case_id")


def test_rejected_high_dti_end_to_end(sample_applications, graph_with_mocked_mcp):
    """APP-TEST-003 should produce verdict=REJECTED."""
    graph, _ = graph_with_mocked_mcp
    initial_state = _scenario_input(sample_applications, "APP-TEST-003")

    final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": "it-rejected-high-dti"}})

    assert final_state["verdict"] == "REJECTED"
    assert final_state.get("case_id")


def test_review_required_borderline_end_to_end(sample_applications, graph_with_mocked_mcp):
    """APP-TEST-004 should produce verdict=REVIEW_REQUIRED."""
    graph, _ = graph_with_mocked_mcp
    initial_state = _scenario_input(sample_applications, "APP-TEST-004")

    final_state = graph.invoke(initial_state, config={"configurable": {"thread_id": "it-review-required"}})

    assert final_state["verdict"] == "REVIEW_REQUIRED"
    assert final_state.get("case_id")
    assert final_state.get("action_taken") == "MANUAL_REVIEW_INITIATED"
    assert final_state.get("notification_status") == "SENT_DISPLAY"
    assert final_state.get("review_queue") == "UNDERWRITING_MEDIUM_RISK"
    assert final_state.get("manual_review_owner") == "unassigned"
    assert final_state.get("reviewer_role") == "UNDERWRITER_L2"
    assert final_state.get("review_due_timestamp")
    assert final_state.get("review_status") == "QUEUED"
    assert final_state.get("status_transition") == "REVIEW_REQUIRED_CREATED_TO_QUEUED"
    assert isinstance(final_state.get("transition_history"), list)
    assert len(final_state.get("transition_history", [])) > 0


def test_case_id_generated_for_all_scenarios(sample_applications, graph_with_mocked_mcp):
    """Every scenario should produce a non-empty case_id."""
    graph, _ = graph_with_mocked_mcp

    for scenario in sample_applications:
        applicant_payload = scenario["input"]
        thread_id = f"it-case-{applicant_payload['applicant_id']}"
        final_state = graph.invoke(applicant_payload, config={"configurable": {"thread_id": thread_id}})

        assert final_state.get("case_id")
