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


@pytest.fixture
def client():
    """Create a TestClient with the FastAPI app."""
    pytest.skip("Will be implemented in Phase 9")


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


@pytest.mark.skip(reason="Will be implemented in Phase 9 after API is complete")
def test_health_endpoint_returns_200(client):
    """GET /health should return 200 with status=ok."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after API is complete")
def test_analyze_valid_request_returns_200(client, valid_request_body):
    """Valid payload should return HTTP 200 with LoanDecisionResponse schema."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after API is complete")
def test_analyze_missing_field_returns_422(client, valid_request_body):
    """Missing required field should return HTTP 422."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after API is complete")
def test_analyze_invalid_credit_score_returns_422(client, valid_request_body):
    """credit_score > 900 should return HTTP 422."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after API is complete")
def test_analyze_response_contains_case_id(client, valid_request_body):
    """Response must include a non-empty case_id field."""
    pass
