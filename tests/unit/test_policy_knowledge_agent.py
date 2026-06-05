"""
tests/unit/test_policy_knowledge_agent.py
==========================================
Unit tests for the Policy Knowledge Agent.

Tests verify:
- ChromaDB retrieval is called with correct query
- Returned chunks are filtered to applicable ones only
- Sources list contains document names
- Empty retrieval returns empty applicable_clauses
"""

import pytest


@pytest.mark.skip(reason="Will be implemented in Phase 9 after agent logic is complete")
def test_retriever_called_with_query():
    """retrieve_policy_chunks should be called once with the built query."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after agent logic is complete")
def test_applicable_clauses_non_empty_for_valid_context():
    """Valid applicant context should return at least one applicable clause."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after agent logic is complete")
def test_sources_list_contains_document_names():
    """sources field should contain .txt filenames from knowledge_base."""
    pass


@pytest.mark.skip(reason="Will be implemented in Phase 9 after agent logic is complete")
def test_empty_retrieval_returns_empty_clauses():
    """If ChromaDB returns no chunks, applicable_clauses should be empty list."""
    pass
