"""
rag/policy_search.py
====================
High-level policy search utilities for the Loan Approval RAG pipeline.

Responsibilities:
- Build a rich semantic query string from structured applicant context
- Call the retriever and filter results by relevance distance threshold
- Format retrieved chunks into the structured dict the Policy Agent expects
- Provide a single search() function as the entry point for all callers

Why this module exists (separation of concerns):
    retriever.py  — knows ChromaDB; takes a query string, returns raw chunks
    policy_search.py — knows loan domain; converts applicant context into a
                       query, filters noise, formats output for the agent

    This means: swapping ChromaDB for Pinecone only touches retriever.py.
    Changing the query-building strategy only touches this file.
    The Policy Knowledge Agent calls search() and never touches retriever.py.

Query construction strategy:
    A natural-language query is built from the applicant's risk profile:
        "Applicant with {credit_band} credit score, DTI {dti:.2%},
         {employment_band} employment, loan amount INR {loan_amount:,.0f},
         {loan_tenure} months. Risk flags: {risk_flags}."

    This narrative form works better than keyword search for semantic
    embeddings because the model was trained on sentence-level context,
    not keyword bags. Including numeric values anchors retrieval to
    threshold-relevant policy clauses.

Distance filtering:
    ChromaDB's cosine distance ranges from 0.0 (identical) to 2.0 (opposite).
    Empirically, chunks with distance > 0.85 are semantically unrelated to
    the query. We filter these out before passing context to the LLM to
    avoid injecting irrelevant policy text into the decision prompt.
"""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from rag.retriever import retrieve_policy_chunks
from utils.logger import get_logger

log = get_logger(__name__, component="policy_search")

# Distance threshold above which a chunk is considered not relevant.
# Cosine distance: 0.0 = identical vectors, 2.0 = orthogonal.
# Chunks above this threshold are filtered out before LLM context assembly.
_MAX_RELEVANCE_DISTANCE = 0.85


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def build_policy_query(
    credit_band: str,
    dti: float,
    employment_band: str,
    loan_amount: float,
    loan_tenure: int,
    risk_flags: list[str],
) -> str:
    """
    Build a natural-language semantic query from structured applicant context.

    Converts numerical and categorical applicant features into a sentence
    that the embedding model can match against policy document embeddings.

    Why natural language over keyword query:
        The all-MiniLM-L6-v2 model was trained on sentence pairs for semantic
        similarity. A sentence like "fair credit score high DTI salaried
        employee personal loan" activates the same latent space as policy
        text discussing "applicants with fair CIBIL scores and elevated
        debt-to-income ratios". Raw keywords like "fair 0.52 salaried 500000"
        do not.

    Args:
        credit_band:     Credit quality band — excellent | good | fair | poor
        dti:             Debt-to-income ratio e.g. 0.45
        employment_band: Employment stability — stable | moderate | unstable
        loan_amount:     Requested loan amount in INR
        loan_tenure:     Repayment period in months
        risk_flags:      List of active risk trigger codes

    Returns:
        Natural-language query string for ChromaDB retrieval.

    Example:
        query = build_policy_query(
            credit_band="fair", dti=0.52, employment_band="moderate",
            loan_amount=500000, loan_tenure=36, risk_flags=["high_dti"]
        )
        # "Applicant with fair credit score, DTI 52.00%, moderate employment
        #  stability, requesting INR 500,000 loan for 36 months.
        #  Risk concerns: high_dti. Relevant credit and income policies apply."
    """
    dti_pct     = f"{dti:.2%}"
    amount_fmt  = f"INR {loan_amount:,.0f}"
    flags_str   = ", ".join(risk_flags) if risk_flags else "none"

    query = (
        f"Applicant with {credit_band} credit score, "
        f"debt-to-income ratio of {dti_pct}, "
        f"{employment_band} employment stability, "
        f"requesting {amount_fmt} loan for {loan_tenure} months. "
        f"Risk concerns: {flags_str}. "
        f"Applicable credit policy, income guidelines, and risk thresholds."
    )

    log.debug("policy_query_built", query=query)
    return query


# ---------------------------------------------------------------------------
# Chunk formatter
# ---------------------------------------------------------------------------

def format_chunks_for_prompt(chunks: list[dict[str, Any]]) -> str:
    """
    Format a list of retrieved chunks into a numbered block for the LLM prompt.

    Each chunk is rendered as:
        [Source: credit_policy.txt | Relevance: 0.1823]
        <chunk text>

    This format makes the source attribution visible to Claude so it can
    cite specific policy documents in its applicable_clauses output.

    Args:
        chunks: List of chunk dicts from retrieve_policy_chunks().
                Each dict has: text, source, chunk_id, distance.

    Returns:
        Formatted multi-line string ready to be injected into the
        policy_knowledge.txt prompt at the {policy_chunks} placeholder.
        Returns "No relevant policy chunks retrieved." if chunks is empty.
    """
    if not chunks:
        return "No relevant policy chunks retrieved."

    lines = []
    for i, chunk in enumerate(chunks, start=1):
        source   = chunk.get("source", "unknown")
        distance = chunk.get("distance", 0.0)
        text     = chunk.get("text", "").strip()

        lines.append(
            f"[Chunk {i} | Source: {source} | Relevance distance: {distance:.4f}]\n"
            f"{text}"
        )

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Primary search function
# ---------------------------------------------------------------------------

def search(
    credit_band: str,
    dti: float,
    employment_band: str,
    loan_amount: float,
    loan_tenure: int,
    risk_flags: list[str],
    top_k: int | None = None,
) -> dict[str, Any]:
    """
    High-level policy search: build query → retrieve → filter → format.

    This is the single function the Policy Knowledge Agent calls.
    It orchestrates query construction, ChromaDB retrieval, relevance
    filtering, and output formatting into one clean interface.

    Args:
        credit_band:     Credit quality band string.
        dti:             Debt-to-income ratio (0.0–1.0+).
        employment_band: Employment stability band string.
        loan_amount:     Requested loan amount in INR.
        loan_tenure:     Repayment period in months.
        risk_flags:      Active risk trigger codes from RiskAgentOutput.
        top_k:           Number of chunks to retrieve. Defaults to
                         settings.rag_top_k (from loan_rules.yaml, default 5).

    Returns:
        Dict with keys:
            {
                "query":           str        — the query string that was used
                "raw_chunks":      list[dict] — unfiltered ChromaDB results
                "filtered_chunks": list[dict] — results passing distance filter
                "formatted_text":  str        — formatted block for LLM prompt
                "sources":         list[str]  — distinct source filenames
                "chunks_retrieved":int        — count before filtering
                "chunks_used":     int        — count after filtering
            }

    Usage:
        from rag.policy_search import search
        result = search(
            credit_band="fair", dti=0.52, employment_band="moderate",
            loan_amount=500000, loan_tenure=36, risk_flags=["high_dti"]
        )
        print(result["formatted_text"])
        print(result["sources"])
    """
    settings = get_settings()
    effective_top_k = top_k if top_k is not None else settings.rag_top_k

    log.info(
        "policy_search_started",
        credit_band=credit_band,
        dti=round(dti, 4),
        employment_band=employment_band,
        loan_amount=loan_amount,
        top_k=effective_top_k,
        risk_flags=risk_flags,
    )

    # ------------------------------------------------------------------
    # Step 1: Build semantic query
    # ------------------------------------------------------------------
    query = build_policy_query(
        credit_band=credit_band,
        dti=dti,
        employment_band=employment_band,
        loan_amount=loan_amount,
        loan_tenure=loan_tenure,
        risk_flags=risk_flags,
    )

    # ------------------------------------------------------------------
    # Step 2: Retrieve from ChromaDB
    # ------------------------------------------------------------------
    raw_chunks = retrieve_policy_chunks(query=query, top_k=effective_top_k)

    # ------------------------------------------------------------------
    # Step 3: Filter by relevance distance threshold
    # Distance is cosine distance: 0.0 = most similar, 2.0 = least similar
    # Chunks with distance > _MAX_RELEVANCE_DISTANCE are off-topic noise
    # ------------------------------------------------------------------
    filtered_chunks = [
        c for c in raw_chunks
        if c.get("distance", 1.0) <= _MAX_RELEVANCE_DISTANCE
    ]

    if not filtered_chunks and raw_chunks:
        # Fallback: if all chunks are filtered out, keep the single best one
        # so the LLM always has at least some policy context
        filtered_chunks = raw_chunks[:1]
        log.warning(
            "all_chunks_filtered_fallback",
            best_distance=raw_chunks[0].get("distance"),
            threshold=_MAX_RELEVANCE_DISTANCE,
        )

    # ------------------------------------------------------------------
    # Step 4: Format for prompt injection
    # ------------------------------------------------------------------
    formatted_text = format_chunks_for_prompt(filtered_chunks)

    # Deduplicate sources preserving order
    seen: set[str] = set()
    sources: list[str] = []
    for c in filtered_chunks:
        src = c.get("source", "unknown")
        if src not in seen:
            seen.add(src)
            sources.append(src)

    log.info(
        "policy_search_complete",
        chunks_retrieved=len(raw_chunks),
        chunks_used=len(filtered_chunks),
        sources=sources,
    )

    return {
        "query":            query,
        "raw_chunks":       raw_chunks,
        "filtered_chunks":  filtered_chunks,
        "formatted_text":   formatted_text,
        "sources":          sources,
        "chunks_retrieved": len(raw_chunks),
        "chunks_used":      len(filtered_chunks),
    }
