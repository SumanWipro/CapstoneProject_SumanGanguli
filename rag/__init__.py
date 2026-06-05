"""
rag/__init__.py
===============
RAG (Retrieval-Augmented Generation) package for the Loan Approval System.

Public API:
    ingest_documents()        — load, chunk, embed, store policy docs
    retrieve_policy_chunks()  — low-level ChromaDB vector search
    search()                  — high-level domain-aware policy search
    collection_health_check() — RAG layer readiness probe
"""

from rag.ingest import ingest_documents
from rag.retriever import retrieve_policy_chunks, collection_health_check
from rag.policy_search import search as policy_search
from rag.embeddings import get_embedding_function

__all__ = [
    "ingest_documents",
    "retrieve_policy_chunks",
    "collection_health_check",
    "policy_search",
    "get_embedding_function",
]
