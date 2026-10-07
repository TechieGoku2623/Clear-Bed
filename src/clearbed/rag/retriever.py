"""Retrieve knowledge-base chunks with a similarity floor.

Chunks below ``RAG_MIN_SIMILARITY`` are dropped. Instructions embedded in a
document are not followed; callers quote sanitized excerpts and keep actions
in their own templates.
"""

from __future__ import annotations

import os
import re
from typing import Any

from clearbed.config import Settings, get_settings
from clearbed.rag.ingest_kb import COLLECTION, embed_texts

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

INJECTION_PATTERN = re.compile(
    r"ignore (all|previous|prior) instructions|\bPWNED\b|auto-?send the referral|system prompt",
    re.IGNORECASE,
)


def sanitize_excerpt(text: str) -> str:
    """Drop lines that try to instruct the agent instead of stating a rule."""
    kept = [line for line in text.splitlines() if not INJECTION_PATTERN.search(line)]
    return "\n".join(kept).strip()


def retrieve(
    query: str,
    *,
    k: int = 5,
    filter_jurisdiction: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``k`` chunks with source URL and similarity."""
    import chromadb

    settings = settings or get_settings()
    if not settings.resolved_chroma_dir.exists():
        return []
    client = chromadb.PersistentClient(path=str(settings.resolved_chroma_dir))
    try:
        collection = client.get_collection(COLLECTION)
    except Exception:  # noqa: BLE001
        return []
    embedding: Any = embed_texts([query], settings.embedding_model)
    where: Any = {"jurisdiction": filter_jurisdiction} if filter_jurisdiction else None
    result = collection.query(query_embeddings=embedding, n_results=k, where=where)
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    chunks: list[dict[str, Any]] = []
    for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
        similarity = 1.0 - float(distance)
        if similarity < settings.rag_min_similarity:
            continue
        meta = metadata or {}
        chunks.append(
            {
                "text": sanitize_excerpt(document or ""),
                "title": meta.get("title", ""),
                "source_url": meta.get("source_url", ""),
                "jurisdiction": meta.get("jurisdiction", ""),
                "doc_id": meta.get("doc_id", ""),
                "similarity": round(similarity, 4),
            }
        )
    return chunks
