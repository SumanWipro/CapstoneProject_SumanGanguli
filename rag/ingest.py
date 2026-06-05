"""
rag/ingest.py
=============
Document ingestion pipeline for the Loan Approval RAG system.

Responsibilities:
- Load all .txt policy documents from knowledge_base/
- Split each document into overlapping fixed-size character chunks
- Store chunks in ChromaDB with source and positional metadata
- Idempotent: deletes and recreates the collection on each run

Pipeline:
    knowledge_base/*.txt
        → load_documents()           reads raw text per file
        → chunk_document()           sliding-window character chunks
        → ChromaDB.add()             embeds and stores via embedding function
        → collection ready for query

Chunking strategy — why fixed-size character windows with overlap:
    Policy documents are dense paragraphs of legal/financial text without
    clean semantic boundaries (no headers per clause, no JSON structure).
    Semantic chunking (split on meaning) requires an extra LLM call per
    document. Fixed-size with 100-character overlap is sufficient because:
    1. Overlap preserves clause continuity across boundaries
    2. 500 chars ≈ 3–4 sentences — fits well within a retrieval context
    3. Deterministic and fast — no extra model call needed at ingest time

Idempotency:
    The collection is deleted and recreated on each run. This means
    re-running ingest after editing a policy document always produces a
    clean, consistent vector store without stale chunks.

Run with:
    python -m rag.ingest
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import chromadb

from config.settings import get_settings
from rag.embeddings import get_embedding_function
from utils.logger import get_logger

log = get_logger(__name__, component="ingest")

# ---------------------------------------------------------------------------
# Constants (overridable via loan_rules.yaml → agents.rag)
# ---------------------------------------------------------------------------

_KB_DIR      = Path(__file__).resolve().parent.parent / "knowledge_base"
_CHUNK_SIZE  = 500    # characters per chunk
_CHUNK_OVERLAP = 100  # characters of overlap between consecutive chunks


# ---------------------------------------------------------------------------
# Step 1: Document loader
# ---------------------------------------------------------------------------

def load_documents() -> list[dict[str, Any]]:
    """
    Load all .txt files from knowledge_base/ as raw document dicts.

    Each .txt file in knowledge_base/ becomes one document. The filename
    is preserved as the "source" metadata field so retrieval results can
    be traced back to their origin document.

    Returns:
        List of document dicts, one per .txt file:
            {
                "content": str  — full raw file text (UTF-8)
                "source":  str  — filename e.g. "credit_policy.txt"
            }
        Returns empty list if knowledge_base/ contains no .txt files.

    Raises:
        FileNotFoundError: If the knowledge_base/ directory does not exist.

    Example:
        docs = load_documents()
        # [{"content": "CREDIT POLICY...", "source": "credit_policy.txt"}, ...]
    """
    if not _KB_DIR.exists():
        raise FileNotFoundError(
            f"knowledge_base directory not found at {_KB_DIR}. "
            "Ensure the project structure is intact."
        )

    txt_files = sorted(_KB_DIR.glob("*.txt"))

    if not txt_files:
        log.warning("no_txt_files_found", directory=str(_KB_DIR))
        return []

    documents = []
    for path in txt_files:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            log.warning("empty_policy_file", file=path.name)
            continue
        documents.append({"content": content, "source": path.name})
        log.info("document_loaded", source=path.name, chars=len(content))

    log.info("documents_loaded_total", count=len(documents))
    return documents


# ---------------------------------------------------------------------------
# Step 2: Chunker
# ---------------------------------------------------------------------------

def chunk_document(content: str, source: str) -> list[dict[str, Any]]:
    """
    Split a document into overlapping fixed-size character chunks.

    Uses a sliding window approach:
        window_start = 0
        window_end   = window_start + CHUNK_SIZE
        next_start   = window_start + (CHUNK_SIZE - CHUNK_OVERLAP)

    This means consecutive chunks share the last CHUNK_OVERLAP characters,
    ensuring that sentences split across a chunk boundary appear in full
    in at least one of the two chunks.

    Empty chunks (e.g. whitespace-only) are skipped.

    Args:
        content: Full document text (UTF-8 string).
        source:  Source filename for chunk metadata (e.g. "credit_policy.txt").

    Returns:
        List of chunk dicts:
            {
                "text":       str  — chunk text (stripped of leading/trailing whitespace)
                "source":     str  — source filename
                "chunk_id":   str  — unique identifier "{source}_{index}"
                "chunk_index":int  — 0-based position within document
            }
        Returns single chunk if content is shorter than CHUNK_SIZE.

    Example:
        chunks = chunk_document("CREDIT POLICY...", "credit_policy.txt")
        # [{"text": "CREDIT POLICY...", "source": "credit_policy.txt",
        #   "chunk_id": "credit_policy.txt_0", "chunk_index": 0}, ...]
    """
    chunks = []
    step   = max(1, _CHUNK_SIZE - _CHUNK_OVERLAP)  # always advance at least 1 char
    index  = 0
    start  = 0

    while start < len(content):
        end  = start + _CHUNK_SIZE
        text = content[start:end].strip()

        if text:  # skip whitespace-only segments
            chunks.append({
                "text":        text,
                "source":      source,
                "chunk_id":    f"{source}_{index}",
                "chunk_index": index,
            })
            index += 1

        start += step

    log.debug(
        "document_chunked",
        source=source,
        total_chars=len(content),
        chunks_produced=len(chunks),
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    return chunks


# ---------------------------------------------------------------------------
# Step 3: Full ingest pipeline
# ---------------------------------------------------------------------------

def ingest_documents() -> int:
    """
    Run the full ingestion pipeline: load → chunk → embed → store.

    Steps:
        1. Load all .txt files from knowledge_base/
        2. Chunk each document using sliding-window strategy
        3. Delete the existing ChromaDB collection (idempotent)
        4. Create a new collection with cosine distance metric
        5. Add all chunks in batches (ChromaDB handles embedding internally)

    Returns:
        Total number of chunks stored in ChromaDB.

    Raises:
        FileNotFoundError: If knowledge_base/ does not exist.
        RuntimeError:      If ChromaDB collection creation fails.

    Usage:
        from rag.ingest import ingest_documents
        count = ingest_documents()
        print(f"Stored {count} chunks")
    """
    settings = get_settings()

    # Read chunk config from loan_rules.yaml if available
    rag_cfg    = settings.loan_rules.get("agents", {}).get("rag", {})
    chunk_size = int(rag_cfg.get("chunk_size", _CHUNK_SIZE))
    overlap    = int(rag_cfg.get("chunk_overlap", _CHUNK_OVERLAP))

    # Override module-level defaults if config differs
    global _CHUNK_SIZE, _CHUNK_OVERLAP
    _CHUNK_SIZE, _CHUNK_OVERLAP = chunk_size, overlap

    log.info(
        "starting_document_ingestion",
        source_dir=str(_KB_DIR),
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        collection=settings.chroma_collection_name,
    )

    # ------------------------------------------------------------------
    # Load documents
    # ------------------------------------------------------------------
    documents = load_documents()
    if not documents:
        log.warning("no_documents_to_ingest")
        return 0

    # ------------------------------------------------------------------
    # Chunk all documents
    # ------------------------------------------------------------------
    all_chunks: list[dict[str, Any]] = []
    for doc in documents:
        chunks = chunk_document(doc["content"], doc["source"])
        all_chunks.extend(chunks)

    log.info("chunking_complete", total_chunks=len(all_chunks))

    # ------------------------------------------------------------------
    # Connect to ChromaDB and recreate collection (idempotent)
    # ------------------------------------------------------------------
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    ef     = get_embedding_function()

    # Delete existing collection to ensure clean state
    try:
        client.delete_collection(name=settings.chroma_collection_name)
        log.info(
            "existing_collection_deleted",
            collection=settings.chroma_collection_name,
        )
    except Exception:
        pass  # Collection didn't exist — first run

    # Create fresh collection with cosine distance metric
    collection = client.create_collection(
        name=settings.chroma_collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for policy text
    )

    log.info(
        "collection_created",
        collection=settings.chroma_collection_name,
        distance_metric="cosine",
    )

    # ------------------------------------------------------------------
    # Add chunks in batches to avoid memory spikes
    # ------------------------------------------------------------------
    _BATCH_SIZE = 50

    for batch_start in range(0, len(all_chunks), _BATCH_SIZE):
        batch = all_chunks[batch_start : batch_start + _BATCH_SIZE]

        collection.add(
            ids       = [c["chunk_id"] for c in batch],
            documents = [c["text"] for c in batch],
            metadatas = [
                {
                    "source":      c["source"],
                    "chunk_index": c["chunk_index"],
                }
                for c in batch
            ],
        )

        log.debug(
            "batch_added",
            batch_start=batch_start,
            batch_size=len(batch),
        )

    final_count = collection.count()
    log.info(
        "ingestion_complete",
        chunks_stored=final_count,
        documents_processed=len(documents),
        collection=settings.chroma_collection_name,
    )
    return final_count


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    count = ingest_documents()
    print(f"\nIngestion complete — {count} chunks stored in ChromaDB.")
    print("Run `python -m rag.retriever` to test retrieval.")
