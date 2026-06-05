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

FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "sample_applications.json"


@pytest.fixture
def sample_applications():
    with open(FIXTURES_PATH) as f:
        return json.load(f)


@pytest.mark.skip(reason="Will be implemented in Phase 9 after full pipeline is complete")
def test_approved_scenario_end_to_end(sample_applications):
    """APP-TEST-001 should produce verdict=APPROVED."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after full pipeline is complete")
def test_rejected_low_credit_end_to_end(sample_applications):
    """APP-TEST-002 should produce verdict=REJECTED."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after full pipeline is complete")
def test_rejected_high_dti_end_to_end(sample_applications):
    """APP-TEST-003 should produce verdict=REJECTED."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after full pipeline is complete")
def test_review_required_borderline_end_to_end(sample_applications):
    """APP-TEST-004 should produce verdict=REVIEW_REQUIRED."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after full pipeline is complete")
def test_case_id_generated_for_all_scenarios(sample_applications):
    """Every scenario should produce a non-empty case_id."""
    pass
