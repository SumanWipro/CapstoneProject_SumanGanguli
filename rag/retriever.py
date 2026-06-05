"""
rag/retriever.py
================
ChromaDB retrieval service for the Loan Approval RAG pipeline.

Responsibilities:
- Provide a persistent ChromaDB client factory
- Expose retrieve_policy_chunks() as the single retrieval entry point
- Return ranked results with text, source metadata, and distance scores
- Raise informative errors when the collection has not been ingested

Why stateless client per call:
    ChromaDB's PersistentClient is lightweight to open — it memory-maps
    its on-disk index rather than loading it fully into RAM. Opening it
    per call avoids connection lifecycle issues in async FastAPI contexts
    (e.g. stale clients after fork, thread-safety concerns with shared
    state). For high-throughput production use, wrap in a connection pool.

Why cosine distance:
    Policy text matching benefits from direction-based similarity (topical
    relevance) rather than magnitude-based (document length independence).
    ChromaDB defaults to L2 distance; we override to cosine at collection
    creation time in ingest.py.
"""

from __future__ import annotations

from typing import Any

import chromadb

from config.settings import get_settings
from rag.embeddings import get_embedding_function
from utils.logger import get_logger

log = get_logger(__name__, component="retriever")


# ---------------------------------------------------------------------------
# ChromaDB client factory
# ---------------------------------------------------------------------------

def get_chroma_client() -> chromadb.PersistentClient:
    """
    Create and return a ChromaDB PersistentClient for the configured path.

    Opens the same on-disk store that ingest.py wrote to. Calling this
    multiple times is safe — each call opens a read-capable handle to the
    same underlying data files.

    Returns:
        chromadb.PersistentClient pointed at settings.chroma_persist_dir.

    Raises:
        RuntimeError: If the persist directory does not exist (ingest not run).
    """
    settings = get_settings()
    persist_dir = settings.chroma_persist_dir

    log.debug("opening_chroma_client", persist_dir=persist_dir)
    return chromadb.PersistentClient(path=persist_dir)


def get_policy_collection() -> chromadb.Collection:
    """
    Return the loan_policy_docs ChromaDB collection.

    The collection must have been created and populated by rag/ingest.py
    before this function is called.

    Returns:
        chromadb.Collection for policy document embeddings.

    Raises:
        ValueError: If the collection does not exist (ingest.py not yet run).
    """
    settings = get_settings()
    client = get_chroma_client()
    ef = get_embedding_function()

    try:
        collection = client.get_collection(
            name=settings.chroma_collection_name,
            embedding_function=ef,
        )
        log.debug(
            "policy_collection_opened",
            collection=settings.chroma_collection_name,
            count=collection.count(),
        )
        return collection

    except Exception as exc:
        raise ValueError(
            f"ChromaDB collection '{settings.chroma_collection_name}' not found. "
            "Run `python -m rag.ingest` to populate the vector store."
        ) from exc


# ---------------------------------------------------------------------------
# Primary retrieval function
# ---------------------------------------------------------------------------

def retrieve_policy_chunks(
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Retrieve the top-k most semantically relevant policy chunks for a query.

    Embeds the query using the shared embedding function, runs a cosine
    similarity search against the ChromaDB collection, and returns ranked
    results with text, source metadata, and similarity distance.

    Args:
        query: Natural language query describing the applicant context.
               Example: "salaried applicant good credit score low DTI
                         requesting personal loan 500000 INR 36 months"
        top_k: Number of chunks to return. Default 5, max 20.
               Matches settings.rag_top_k from loan_rules.yaml.

    Returns:
        List of result dicts ordered by relevance (most relevant first):
            {
                "text":     str   — policy chunk text
                "source":   str   — source filename e.g. "credit_policy.txt"
                "chunk_id": str   — unique chunk identifier
                "distance": float — cosine distance (0.0 = identical,
                                    2.0 = opposite; lower = more relevant)
            }
        Returns empty list if the collection is empty.

    Raises:
        ValueError: If the ChromaDB collection does not exist.

    Usage:
        from rag.retriever import retrieve_policy_chunks
        results = retrieve_policy_chunks(
            query="fair credit score high DTI salaried personal loan",
            top_k=5,
        )
        for r in results:
            print(r["source"], r["distance"], r["text"][:80])
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    top_k = max(1, min(top_k, 20))  # clamp to [1, 20]

    log.info(
        "retrieve_policy_chunks_called",
        query_preview=query[:80],
        top_k=top_k,
    )

    collection = get_policy_collection()

    if collection.count() == 0:
        log.warning("policy_collection_empty")
        return []

    # ChromaDB query — returns results sorted by distance (ascending)
    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    # Unpack ChromaDB's batched response format (index 0 = first query)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    ids       = results.get("ids", [[]])[0]

    chunks = []
    for doc, meta, dist, chunk_id in zip(documents, metadatas, distances, ids):
        chunks.append({
            "text":     doc,
            "source":   meta.get("source", "unknown"),
            "chunk_id": chunk_id,
            "distance": round(float(dist), 6),
        })

    log.info(
        "retrieve_policy_chunks_complete",
        top_k=top_k,
        returned=len(chunks),
        best_distance=chunks[0]["distance"] if chunks else None,
    )

    return chunks


# ---------------------------------------------------------------------------
# Utility: collection health check
# ---------------------------------------------------------------------------

def collection_health_check() -> dict[str, Any]:
    """
    Return basic health information about the policy collection.

    Used by the GET /health endpoint to confirm the RAG layer is ready.

    Returns:
        Dict with keys:
            - status  (str):  "ready" | "empty" | "missing"
            - count   (int):  Number of chunks in the collection
            - sources (list): Distinct source filenames present
    """
    settings = get_settings()
    try:
        collection = get_policy_collection()
        count = collection.count()

        if count == 0:
            return {"status": "empty", "count": 0, "sources": []}

        # Sample metadata to list distinct sources
        sample = collection.get(limit=count, include=["metadatas"])
        sources = sorted({
            m.get("source", "unknown")
            for m in (sample.get("metadatas") or [])
        })

        return {
            "status":  "ready",
            "count":   count,
            "sources": sources,
        }

    except ValueError:
        return {
            "status":  "missing",
            "count":   0,
            "sources": [],
            "message": f"Collection '{settings.chroma_collection_name}' not found. "
                       "Run `python -m rag.ingest`.",
        }
