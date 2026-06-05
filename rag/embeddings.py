"""
rag/embeddings.py
=================
Embedding model service for the Loan Approval RAG pipeline.

Responsibilities:
- Load and cache the sentence-transformers embedding model exactly once
- Expose a ChromaDB-compatible EmbeddingFunction singleton used by both
  ingest.py (at write time) and retriever.py (at query time)
- Guarantee that ingestion and retrieval share the same vector space

Why sentence-transformers/all-MiniLM-L6-v2:
- Lightweight (~80 MB) — runs on CPU without GPU
- Produces 384-dimensional embeddings — compact and fast for small corpora
- Pre-trained on semantic similarity — well-suited for matching policy text
  to natural language queries
- Fully offline — no API call needed per embedding

Why the same function for ingest and retrieval:
  Embeddings are dot-product comparable only within the same vector space.
  If ingest uses model A and retrieval uses model B, all similarity scores
  are meaningless. The singleton lru_cache enforces this at runtime.

Production upgrade path:
  Replace _MODEL_NAME with a Bedrock Titan embedding model ID and swap
  SentenceTransformerEmbeddingFunction for a custom BedrockEmbeddingFunction
  that wraps boto3 Bedrock's embed_text API. The rest of the pipeline
  (ingest, retriever, policy_search) requires zero changes.
"""

from __future__ import annotations

from functools import lru_cache

from chromadb.utils import embedding_functions
from utils.logger import get_logger

log = get_logger(__name__, component="embeddings")

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

# sentence-transformers model name — must match on both ingest and retrieval
_MODEL_NAME = "all-MiniLM-L6-v2"

# ChromaDB will download the model to ~/.cache/torch/sentence_transformers/
# on first use. Subsequent runs load from cache.
_CACHE_DIR = None  # None = default huggingface cache; set to override


# ---------------------------------------------------------------------------
# Singleton embedding function
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """
    Return the process-wide singleton ChromaDB embedding function.

    The model is loaded from disk (or downloaded) on the first call and
    cached for all subsequent calls via lru_cache. This means the ~80 MB
    model load happens exactly once per process regardless of how many
    times ingest or retrieval is called.

    Returns:
        SentenceTransformerEmbeddingFunction wrapping all-MiniLM-L6-v2.
        Compatible with chromadb collection.add() and collection.query().

    Usage:
        from rag.embeddings import get_embedding_function
        ef = get_embedding_function()

        # During ingestion
        collection = client.get_or_create_collection(
            name="loan_policy_docs",
            embedding_function=ef,
        )

        # During retrieval — same function, same vector space
        collection = client.get_collection(
            name="loan_policy_docs",
            embedding_function=ef,
        )
    """
    log.info("loading_embedding_model", model=_MODEL_NAME)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=_MODEL_NAME,
        cache_folder=_CACHE_DIR,
    )

    log.info("embedding_model_loaded", model=_MODEL_NAME)
    return ef


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text strings and return their vector representations.

    Convenience wrapper around get_embedding_function() for use cases
    where direct vector access is needed (e.g. similarity pre-checks).

    Args:
        texts: List of strings to embed. Must be non-empty.

    Returns:
        List of float vectors, one per input string.
        Each vector has 384 dimensions (all-MiniLM-L6-v2).

    Raises:
        ValueError: If texts is empty.

    Usage:
        from rag.embeddings import embed_texts
        vectors = embed_texts(["low credit score applicant high DTI"])
    """
    if not texts:
        raise ValueError("texts must be a non-empty list")

    ef = get_embedding_function()
    return ef(texts)
