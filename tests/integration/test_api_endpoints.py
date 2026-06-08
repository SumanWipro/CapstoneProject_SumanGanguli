"""
tests/integration/test_api_endpoints.py
=========================================
Integration tests for the FastAPI gateway endpoints.

Uses FastAPI TestClient — no running server required.
LangGraph pipeline is mocked to isolate API layer testing.

Tests verify:
- POST /api/v1/analyze returns 200 with valid payload
- POST /api/v1/analyze returns 422 with missing fields
- POST /api/v1/analyze returns 422 with out-of-range credit score
- GET /health returns 200 {"status": "ok"}
- Response body matches LoanDecisionResponse schema
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.models.response import LoanDecisionResponse


class _FakeGraph:
    """Deterministic LangGraph stub for API-layer tests."""

    def invoke(self, initial_state: dict, config: dict | None = None) -> dict:
        applicant_id = initial_state.get("applicant_id", "APP-UNKNOWN")
        return {
            "applicant_id": applicant_id,
            "verdict": "APPROVED",
            "confidence_score": 0.91,
            "explanation": "Mocked pipeline decision for integration testing.",
            "case_id": "CASE-20260608-0001",
            "risk_result": {
                "risk_score": 22.5,
                "credit_band": "good",
                "dti": 0.12,
            },
            "audit_record": {
                "case_id": "CASE-20260608-0001",
                "log_path": "./audit/logs/2026-06-08.jsonl",
                "notification_summary": "Your application has been approved.",
            },
            "action_result": {
                "action_taken": "NO_ACTION_REQUIRED",
                "notification_status": "SENT_DISPLAY",
                "review_queue": None,
                "manual_review_owner": None,
                "reviewer_role": None,
                "review_due_timestamp": None,
                "review_status": "NOT_REQUIRED",
                "status_transition": "NONE",
                "transition_history": [],
            },
        }


@pytest.fixture
def client(monkeypatch):
    """Create a TestClient with the FastAPI app."""
    import api.main as api_main
    import rag.retriever as rag_retriever

    monkeypatch.setattr(api_main, "_mcp_server_ready", lambda: True)
    monkeypatch.setattr(
        rag_retriever,
        "collection_health_check",
        lambda: {"status": "ready"},
    )

    app = create_app()

    with TestClient(app) as test_client:
        test_client.app.state.graph = _FakeGraph()
        yield test_client


@pytest.fixture
def valid_request_body():
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


def test_health_endpoint_returns_200(client):
    """GET /health should return 200 with status=ok."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "loan-approval-api"
    assert body["version"]


def test_analyze_valid_request_returns_200(client, valid_request_body):
    """Valid payload should return HTTP 200 with LoanDecisionResponse schema."""
    response = client.post("/api/v1/analyze", json=valid_request_body)

    assert response.status_code == 200
    body = response.json()
    parsed = LoanDecisionResponse.model_validate(body)
    assert parsed.applicant_id == valid_request_body["applicant_id"]
    assert parsed.verdict in {"APPROVED", "REJECTED", "REVIEW_REQUIRED"}
    assert 0.0 <= parsed.confidence_score <= 1.0


def test_analyze_missing_field_returns_422(client, valid_request_body):
    """Missing required field should return HTTP 422."""
    bad_payload = dict(valid_request_body)
    bad_payload.pop("loan_amount")

    response = client.post("/api/v1/analyze", json=bad_payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "VALIDATION_ERROR"


def test_analyze_invalid_credit_score_returns_422(client, valid_request_body):
    """credit_score > 900 should return HTTP 422."""
    bad_payload = dict(valid_request_body)
    bad_payload["credit_score"] = 950

    response = client.post("/api/v1/analyze", json=bad_payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "VALIDATION_ERROR"


def test_analyze_response_contains_case_id(client, valid_request_body):
    """Response must include a non-empty case_id field."""
    response = client.post("/api/v1/analyze", json=valid_request_body)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("case_id"), str)
    assert body["case_id"].strip() != ""
