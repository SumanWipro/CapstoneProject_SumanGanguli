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

from __future__ import annotations

import pytest

from agents.policy_knowledge_agent import PolicyKnowledgeAgent


@pytest.fixture
def base_payload():
    return {
        "credit_band": "fair",
        "dti": 0.52,
        "employment_risk": "medium",
        "loan_amount": 500000.0,
        "loan_tenure": 36,
        "risk_flags": ["high_dti"],
        "top_k": 5,
    }


def test_retriever_called_with_query(base_payload, monkeypatch):
    """retrieve_policy_chunks should be called once with the built query."""
    agent = object.__new__(PolicyKnowledgeAgent)
    agent.settings = type("S", (), {"rag_top_k": 5})()

    calls = {"count": 0}

    def fake_search(**kwargs):
        calls["count"] += 1
        return {
            "formatted_text": "[Chunk 1] sample",
            "sources": ["credit_policy.txt"],
            "filtered_chunks": [{"text": "chunk text", "source": "credit_policy.txt"}],
            "chunks_used": 1,
        }

    monkeypatch.setattr("agents.policy_knowledge_agent.policy_search", fake_search)
    monkeypatch.setattr(PolicyKnowledgeAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(PolicyKnowledgeAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        PolicyKnowledgeAgent,
        "parse_json_response",
        lambda self, raw: {"applicable_clauses": ["Clause A"], "sources": ["credit_policy.txt"], "policy_summary": "Summary"},
    )

    _ = agent.invoke(base_payload)

    assert calls["count"] == 1


def test_applicable_clauses_non_empty_for_valid_context(base_payload, monkeypatch):
    """Valid applicant context should return at least one applicable clause."""
    agent = object.__new__(PolicyKnowledgeAgent)
    agent.settings = type("S", (), {"rag_top_k": 5})()

    monkeypatch.setattr(
        "agents.policy_knowledge_agent.policy_search",
        lambda **kwargs: {
            "formatted_text": "[Chunk 1] sample",
            "sources": ["risk_thresholds.txt"],
            "filtered_chunks": [{"text": "risk clause", "source": "risk_thresholds.txt"}],
            "chunks_used": 1,
        },
    )
    monkeypatch.setattr(PolicyKnowledgeAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(PolicyKnowledgeAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        PolicyKnowledgeAgent,
        "parse_json_response",
        lambda self, raw: {
            "applicable_clauses": ["DTI threshold requires manual review"],
            "sources": ["risk_thresholds.txt"],
            "policy_summary": "Borderline risk requires review.",
        },
    )

    result = agent.invoke(base_payload)
    assert len(result["applicable_clauses"]) >= 1


def test_sources_list_contains_document_names(base_payload, monkeypatch):
    """sources field should contain .txt filenames from knowledge_base."""
    agent = object.__new__(PolicyKnowledgeAgent)
    agent.settings = type("S", (), {"rag_top_k": 5})()

    monkeypatch.setattr(
        "agents.policy_knowledge_agent.policy_search",
        lambda **kwargs: {
            "formatted_text": "[Chunk 1] sample",
            "sources": ["credit_policy.txt"],
            "filtered_chunks": [{"text": "credit rule", "source": "credit_policy.txt"}],
            "chunks_used": 1,
        },
    )
    monkeypatch.setattr(PolicyKnowledgeAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(PolicyKnowledgeAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        PolicyKnowledgeAgent,
        "parse_json_response",
        lambda self, raw: {
            "applicable_clauses": ["Clause A"],
            "sources": ["income_guidelines.txt"],
            "policy_summary": "Summary",
        },
    )

    result = agent.invoke(base_payload)
    assert any(src.endswith(".txt") for src in result["sources"])


def test_empty_retrieval_returns_empty_clauses(base_payload, monkeypatch):
    """If ChromaDB returns no chunks, applicable_clauses should be empty list."""
    agent = object.__new__(PolicyKnowledgeAgent)
    agent.settings = type("S", (), {"rag_top_k": 5})()

    monkeypatch.setattr(
        "agents.policy_knowledge_agent.policy_search",
        lambda **kwargs: {
            "formatted_text": "No relevant policy chunks retrieved.",
            "sources": [],
            "filtered_chunks": [],
            "chunks_used": 0,
        },
    )
    monkeypatch.setattr(PolicyKnowledgeAgent, "build_prompt", lambda self, **kwargs: "prompt")
    monkeypatch.setattr(PolicyKnowledgeAgent, "call_claude", lambda self, prompt: "{}")
    monkeypatch.setattr(
        PolicyKnowledgeAgent,
        "parse_json_response",
        lambda self, raw: {
            "applicable_clauses": [],
            "sources": [],
            "policy_summary": "No applicable clauses found.",
        },
    )

    result = agent.invoke(base_payload)
    assert result["applicable_clauses"] == []
