"""
tests/unit/test_orchestrator_mcp_invocation.py
==============================================
Focused tests for orchestrator MCP invocation behavior.

These tests verify that node functions call tools through the MCP client
adapter path and do not rely on direct local tool function imports.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from orchestrator import nodes


class _FakeMCPClient:
    """Simple fake MCP client that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        self.calls.append((tool_name, payload))

        if tool_name == "validate_profile":
            return {
                "income_stability_score": 85.0,
                "employment_risk": "low",
                "credit_history_summary": "Excellent credit history (780)",
                "completeness_flags": [],
            }

        if tool_name == "calculate_risk":
            return {
                "dti": 0.25,
                "credit_band": "good",
                "risk_score": 25.0,
                "risk_flags": [],
            }

        if tool_name == "query_policy":
            return {
                "chunks": [],
                "sources": ["credit_policy.txt"],
                "applicable_clauses": ["Clause A"],
                "policy_summary": "Policy context summary",
            }

        if tool_name == "generate_decision":
            return {
                "verdict": "APPROVED",
                "confidence": 0.88,
                "explanation": "Low risk and policy compliant.",
            }

        if tool_name == "orchestrate_review_action":
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
                "case_id": "CASE-20260606-0001",
                "log_path": "./audit/logs/2026-06-06.jsonl",
                "notification_summary": "Approved and notified.",
            }

        return {}


def _sample_state() -> dict:
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
        "timestamp": "2026-06-06T10:00:00Z",
        "profile_result": None,
        "risk_result": None,
        "policy_chunks": None,
        "decision_result": None,
        "audit_record": None,
        "verdict": None,
        "confidence_score": None,
        "explanation": None,
        "case_id": None,
        "error": None,
        "early_exit": False,
    }


def test_nodes_module_no_direct_tool_function_imports():
    """The nodes module should not expose direct mcp.tools function imports."""
    assert not hasattr(nodes, "validate_profile")
    assert not hasattr(nodes, "calculate_risk")
    assert not hasattr(nodes, "query_policy")
    assert not hasattr(nodes, "generate_decision")
    assert not hasattr(nodes, "create_audit")


def test_applicant_profile_node_calls_validate_profile_via_mcp_client(monkeypatch):
    """applicant_profile_node must call validate_profile via adapter."""
    fake_client = _FakeMCPClient()
    monkeypatch.setattr(nodes, "get_mcp_client", lambda: fake_client)

    result = nodes.applicant_profile_node(_sample_state())

    assert result["early_exit"] is False
    assert result["profile_result"]["employment_risk"] == "low"
    assert result["profile_result"]["completeness_flags"] == []
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0][0] == "validate_profile"


def test_financial_risk_node_sends_employment_risk(monkeypatch):
    """financial_risk_node should send employment_risk (not employment_band)."""
    fake_client = _FakeMCPClient()
    monkeypatch.setattr(nodes, "get_mcp_client", lambda: fake_client)

    state = _sample_state()
    state["profile_result"] = {
        "income_stability_score": 70.0,
        "employment_risk": "medium",
        "credit_history_summary": "Good credit history (720)",
        "completeness_flags": [],
    }

    _ = nodes.financial_risk_node(state)

    # Second call payload (or first in this isolated test) should include employment_risk.
    tool_name, payload = fake_client.calls[0]
    assert tool_name == "calculate_risk"
    assert payload["employment_risk"] == "medium"


def test_end_to_end_node_chain_uses_expected_mcp_tool_names(monkeypatch):
    """Happy-path node chain should call each MCP tool with expected name."""
    fake_client = _FakeMCPClient()
    monkeypatch.setattr(nodes, "get_mcp_client", lambda: fake_client)

    state = _sample_state()

    profile_update = nodes.applicant_profile_node(state)
    state.update(profile_update)

    risk_update = nodes.financial_risk_node(state)
    state.update(risk_update)

    policy_update = nodes.policy_knowledge_node(state)
    state.update(policy_update)

    decision_update = nodes.loan_decision_node(state)
    state.update(decision_update)

    action_update = nodes.review_action_node(state)
    state.update(action_update)

    compliance_update = nodes.compliance_node(state)
    state.update(compliance_update)

    called_tool_names = [name for name, _ in fake_client.calls]

    assert called_tool_names == [
        "validate_profile",
        "calculate_risk",
        "query_policy",
        "generate_decision",
        "orchestrate_review_action",
        "create_audit",
    ]
    assert state["verdict"] == "APPROVED"
    assert state["case_id"] == "CASE-20260606-0001"
