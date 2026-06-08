"""
tests/conftest.py
=================
Shared pytest fixtures and mock factories for the Loan Approval test suite.

Responsibilities:
- Provide reusable applicant payload fixtures for all test modules
- Provide mock factories for AWS Bedrock (boto3) and ChromaDB
- Provide pre-built agent output fixtures (ProfileResult, RiskResult, etc.)
- Configure pytest settings (asyncio mode, test paths)

Design decisions:
- All Bedrock calls are mocked via unittest.mock.patch so no AWS credentials
  are required in CI. The mock returns a realistic Bedrock Messages API
  response shape that matches what real Claude Sonnet returns.
- ChromaDB is mocked at the collection.query() level so no chroma_db/
  directory is required. The mock returns pre-built chunk lists.
- Fixtures follow the scope hierarchy: session > module > function.
  Expensive objects (settings singleton) use session scope; per-test
  payloads use function scope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# pytest configuration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring external services (Bedrock, ChromaDB)",
    )


# ---------------------------------------------------------------------------
# Session-scoped settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def settings():
    """Return the application Settings singleton (parsed once per test session)."""
    from config.settings import get_settings
    return get_settings()


# ---------------------------------------------------------------------------
# Raw applicant payload fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_applicant() -> dict[str, Any]:
    """Standard salaried applicant — expected APPROVED."""
    return {
        "applicant_id":         "APP-TEST-001",
        "age":                  35,
        "income":               1200000.0,
        "employment_type":      "salaried",
        "credit_score":         780,
        "loan_amount":          500000.0,
        "loan_tenure":          36,
        "existing_liabilities": 10000.0,
        "location":             "Mumbai",
        "timestamp":            "2024-01-15T10:30:00Z",
    }


@pytest.fixture
def low_credit_applicant() -> dict[str, Any]:
    """Applicant with credit score < 500 — expected REJECTED."""
    return {
        "applicant_id":         "APP-TEST-002",
        "age":                  28,
        "income":               600000.0,
        "employment_type":      "salaried",
        "credit_score":         450,
        "loan_amount":          300000.0,
        "loan_tenure":          24,
        "existing_liabilities": 5000.0,
        "location":             "Delhi",
        "timestamp":            "2024-01-15T11:00:00Z",
    }


@pytest.fixture
def high_dti_applicant() -> dict[str, Any]:
    """Applicant with DTI > 0.60 — expected REJECTED."""
    return {
        "applicant_id":         "APP-TEST-003",
        "age":                  42,
        "income":               400000.0,
        "employment_type":      "self_employed",
        "credit_score":         650,
        "loan_amount":          800000.0,
        "loan_tenure":          48,
        "existing_liabilities": 25000.0,
        "location":             "Bangalore",
        "timestamp":            "2024-01-15T11:30:00Z",
    }


@pytest.fixture
def borderline_applicant() -> dict[str, Any]:
    """Borderline contract worker — expected REVIEW_REQUIRED."""
    return {
        "applicant_id":         "APP-TEST-004",
        "age":                  31,
        "income":               700000.0,
        "employment_type":      "contract",
        "credit_score":         580,
        "loan_amount":          400000.0,
        "loan_tenure":          36,
        "existing_liabilities": 18000.0,
        "location":             "Pune",
        "timestamp":            "2024-01-15T12:00:00Z",
    }


@pytest.fixture
def overage_applicant() -> dict[str, Any]:
    """Applicant aged 72 — expected REJECTED (age ineligible)."""
    return {
        "applicant_id":         "APP-TEST-005",
        "age":                  72,
        "income":               900000.0,
        "employment_type":      "government",
        "credit_score":         760,
        "loan_amount":          200000.0,
        "loan_tenure":          12,
        "existing_liabilities": 5000.0,
        "location":             "Chennai",
        "timestamp":            "2024-01-15T12:30:00Z",
    }


@pytest.fixture
def government_applicant() -> dict[str, Any]:
    """Government employee with excellent profile — expected APPROVED."""
    return {
        "applicant_id":         "APP-TEST-006",
        "age":                  45,
        "income":               950000.0,
        "employment_type":      "government",
        "credit_score":         755,
        "loan_amount":          1000000.0,
        "loan_tenure":          120,
        "existing_liabilities": 15000.0,
        "location":             "Hyderabad",
        "timestamp":            "2024-01-15T13:00:00Z",
    }


@pytest.fixture
def all_scenarios() -> list[dict[str, Any]]:
    """Load all 6 fixture scenarios from sample_applications.json."""
    with open(FIXTURES_DIR / "sample_applications.json") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Pre-built agent output fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_profile_result() -> dict[str, Any]:
    """ProfileResult for a valid salaried applicant."""
    return {
        "income_stability_score": 85.0,
        "employment_risk": "low",
        "credit_history_summary": "Excellent credit history (780)",
        "completeness_flags": [],
    }


@pytest.fixture
def invalid_profile_result() -> dict[str, Any]:
    """ProfileResult for an ineligible applicant (age > 70)."""
    return {
        "income_stability_score": 35.0,
        "employment_risk": "high",
        "credit_history_summary": "Poor credit history (500)",
        "completeness_flags": ["AGE_INELIGIBLE"],
    }


@pytest.fixture
def low_risk_result() -> dict[str, Any]:
    """RiskResult for a low-risk applicant (APPROVED range)."""
    return {
        "dti":          0.1000,
        "credit_band":  "excellent",
        "risk_score":   20.0,
        "risk_flags":   [],
    }


@pytest.fixture
def high_risk_result() -> dict[str, Any]:
    """RiskResult for a high-risk applicant (REJECTED range)."""
    return {
        "dti":          0.7500,
        "credit_band":  "poor",
        "risk_score":   85.0,
        "risk_flags":   ["high_dti", "poor_credit"],
    }


@pytest.fixture
def medium_risk_result() -> dict[str, Any]:
    """RiskResult for a borderline applicant (REVIEW_REQUIRED range)."""
    return {
        "dti":          0.3086,
        "credit_band":  "fair",
        "risk_score":   55.0,
        "risk_flags":   [],
    }


@pytest.fixture
def policy_chunks_result() -> dict[str, Any]:
    """PolicyChunks with representative applicable clauses."""
    return {
        "chunks": [
            "Applicants with excellent credit (750+) qualify for premium products.",
            "DTI below 0.30 qualifies for low-risk assessment.",
        ],
        "sources": ["credit_policy.txt", "risk_thresholds.txt"],
        "applicable_clauses": [
            "From credit_policy.txt: Excellent credit band qualifies for best rates.",
        ],
        "policy_summary": (
            "Applicant meets all credit and income policy requirements. "
            "No adverse policy clauses apply."
        ),
    }


@pytest.fixture
def approved_decision_result() -> dict[str, Any]:
    return {
        "verdict":     "APPROVED",
        "confidence":  0.87,
        "explanation": "Strong credit score and low DTI meet all approval criteria.",
    }


@pytest.fixture
def rejected_decision_result() -> dict[str, Any]:
    return {
        "verdict":     "REJECTED",
        "confidence":  0.92,
        "explanation": "Credit score below minimum threshold of 500.",
    }


@pytest.fixture
def review_decision_result() -> dict[str, Any]:
    return {
        "verdict":     "REVIEW_REQUIRED",
        "confidence":  0.63,
        "explanation": "Borderline DTI and fair credit require human review.",
    }


@pytest.fixture
def audit_record_result() -> dict[str, Any]:
    return {
        "case_id":              "CASE-20240115-0001",
        "log_path":             "./audit/logs/2024-01-15.jsonl",
        "notification_summary": (
            "Congratulations! Your loan application has been approved. "
            "A loan officer will contact you within 2 business days. "
            "Your Case ID is CASE-20240115-0001."
        ),
    }


# ---------------------------------------------------------------------------
# Bedrock mock factory
# ---------------------------------------------------------------------------

def make_bedrock_client_mock(json_payload: dict[str, Any]) -> MagicMock:
    """
    Return a mock boto3 Bedrock runtime client whose invoke_model() returns
    a realistic Bedrock Messages API response for the given json_payload.

    The response body mirrors what Claude Sonnet returns:
        {"content": [{"type": "text", "text": "<json>"}], "stop_reason": "end_turn"}

    Args:
        json_payload: Dict that Claude should "return" as JSON text.

    Returns:
        MagicMock boto3 client with invoke_model pre-configured.
    """
    bedrock_response_body = {
        "content": [{"type": "text", "text": json.dumps(json_payload)}],
        "stop_reason": "end_turn",
    }
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps(bedrock_response_body).encode()

    mock_client = MagicMock()
    mock_client.invoke_model.return_value = {"body": mock_body}
    return mock_client


@pytest.fixture
def mock_bedrock_approved(
    valid_profile_result,
    low_risk_result,
    policy_chunks_result,
    approved_decision_result,
    audit_record_result,
) -> dict[str, MagicMock]:
    """Bedrock client mocks pre-configured for the APPROVED decision path."""
    return {
        "profile":    make_bedrock_client_mock(valid_profile_result),
        "risk":       make_bedrock_client_mock(low_risk_result),
        "policy":     make_bedrock_client_mock(policy_chunks_result),
        "decision":   make_bedrock_client_mock(approved_decision_result),
        "compliance": make_bedrock_client_mock(
            {"notification_summary": audit_record_result["notification_summary"]}
        ),
    }


@pytest.fixture
def mock_bedrock_rejected(
    invalid_profile_result,
    high_risk_result,
    policy_chunks_result,
    rejected_decision_result,
) -> dict[str, MagicMock]:
    """Bedrock client mocks pre-configured for the REJECTED decision path."""
    return {
        "profile":    make_bedrock_client_mock(invalid_profile_result),
        "risk":       make_bedrock_client_mock(high_risk_result),
        "policy":     make_bedrock_client_mock(policy_chunks_result),
        "decision":   make_bedrock_client_mock(rejected_decision_result),
        "compliance": make_bedrock_client_mock(
            {"notification_summary": "We regret to inform you that your application was rejected."}
        ),
    }


@pytest.fixture
def mock_bedrock_review(
    valid_profile_result,
    medium_risk_result,
    policy_chunks_result,
    review_decision_result,
) -> dict[str, MagicMock]:
    """Bedrock client mocks pre-configured for the REVIEW_REQUIRED decision path."""
    return {
        "profile":    make_bedrock_client_mock(valid_profile_result),
        "risk":       make_bedrock_client_mock(medium_risk_result),
        "policy":     make_bedrock_client_mock(policy_chunks_result),
        "decision":   make_bedrock_client_mock(review_decision_result),
        "compliance": make_bedrock_client_mock(
            {"notification_summary": "Your application has been forwarded for human review."}
        ),
    }


# ---------------------------------------------------------------------------
# ChromaDB mock factory
# ---------------------------------------------------------------------------

def make_chroma_collection_mock(chunks: list[dict[str, Any]] | None = None) -> MagicMock:
    """
    Return a mock ChromaDB collection whose .query() returns the given chunks.

    Args:
        chunks: List of chunk dicts with keys: text, source, chunk_id.
                Defaults to two representative policy chunks.

    Returns:
        MagicMock chromadb collection.
    """
    if chunks is None:
        chunks = [
            {
                "text":     "Applicants with excellent credit qualify for premium products.",
                "source":   "credit_policy.txt",
                "chunk_id": "credit_policy.txt_0",
            },
            {
                "text":     "DTI below 0.30 qualifies as low risk.",
                "source":   "risk_thresholds.txt",
                "chunk_id": "risk_thresholds.txt_0",
            },
        ]

    mock_collection = MagicMock()
    mock_collection.count.return_value = len(chunks)
    mock_collection.query.return_value = {
        "documents": [[c["text"] for c in chunks]],
        "metadatas": [[{"source": c["source"]} for c in chunks]],
        "distances": [[0.15 + i * 0.05 for i in range(len(chunks))]],
        "ids":       [[c["chunk_id"] for c in chunks]],
    }
    return mock_collection


@pytest.fixture
def mock_chroma_collection() -> MagicMock:
    """Pytest fixture wrapping make_chroma_collection_mock with default chunks."""
    return make_chroma_collection_mock()


@pytest.fixture
def mock_empty_chroma_collection() -> MagicMock:
    """ChromaDB collection mock that returns no documents (empty retrieval)."""
    return make_chroma_collection_mock(chunks=[])
