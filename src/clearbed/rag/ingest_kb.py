"""Chunk the curated markdown knowledge base and store embeddings in Chroma.

Embeddings use sentence-transformers ``all-MiniLM-L6-v2``. Re-running replaces
the collection so the index matches the files on disk.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clearbed.config import get_settings
from clearbed.logging import get_logger, log_event

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

logger = get_logger("rag.ingest")
COLLECTION = "clearbed_kb"


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML front matter from a markdown body."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            return dict(meta), parts[2].strip()
    return {}, text.strip()


def chunk_text(text: str, *, max_tokens: int = 500, overlap_tokens: int = 80) -> list[str]:
    """Split ``text`` into word windows of about ``max_tokens`` tokens.

    A token is estimated as 1.3 per word, so 500 tokens is about 380 words.
    """
    words = text.split()
    if not words:
        return []
    max_words = max(int(max_tokens / 1.3), 20)
    overlap_words = max(int(overlap_tokens / 1.3), 0)
    step = max(max_words - overlap_words, 1)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + max_words]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + max_words >= len(words):
            break
    return chunks


@lru_cache(maxsize=1)
def get_encoder(model_name: str) -> Any:
    """Load the sentence-transformer once per process."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    """Embed ``texts`` with the configured MiniLM model."""
    if not texts:
        return []
    encoder = get_encoder(model_name)
    vectors = encoder.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


def load_documents(knowledge_dir: Path) -> list[dict[str, Any]]:
    """Read markdown documents and attach chunk metadata from front matter."""
    documents: list[dict[str, Any]] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        meta, body = parse_markdown(path.read_text(encoding="utf-8"))
        for index, chunk in enumerate(chunk_text(body)):
            documents.append(
                {
                    "id": f"{path.stem}:{index}",
                    "text": chunk,
                    "metadata": {
                        "doc_id": path.stem,
                        "title": str(meta.get("title") or path.stem),
                        "source_url": str(meta.get("source_url") or ""),
                        "last_verified": str(meta.get("last_verified") or ""),
                        "jurisdiction": str(meta.get("jurisdiction") or ""),
                        "status": str(meta.get("status") or ""),
                        "chunk_index": index,
                    },
                }
            )
    return documents


def ingest_directory(knowledge_dir: Path, chroma_dir: Path, model_name: str) -> int:
    """Replace the Chroma collection with the documents in ``knowledge_dir``."""
    import chromadb

    docs = load_documents(knowledge_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        client.delete_collection(COLLECTION)
    except Exception:  # noqa: BLE001
        pass
    collection = client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})
    if not docs:
        return 0
    embeddings = embed_texts([doc["text"] for doc in docs], model_name)
    stored: Any = embeddings
    collection.upsert(
        ids=[doc["id"] for doc in docs],
        documents=[doc["text"] for doc in docs],
        metadatas=[doc["metadata"] for doc in docs],
        embeddings=stored,
    )
    log_event(logger, "ingested knowledge base", chunks=len(docs))
    return len(docs)


def catalog(knowledge_dir: Path) -> dict[str, dict[str, str]]:
    """Return front matter keyed by file stem, for citations that do not need a search."""
    found: dict[str, dict[str, str]] = {}
    for path in knowledge_dir.glob("*.md"):
        meta, _body = parse_markdown(path.read_text(encoding="utf-8"))
        found[path.stem] = {key: str(value) for key, value in meta.items()}
    return found


def main() -> None:
    """Embed the configured knowledge directory."""
    settings = get_settings()
    count = ingest_directory(
        settings.resolved_knowledge_dir,
        settings.resolved_chroma_dir,
        settings.embedding_model,
    )
    print(f"Embedded {count} chunks into {settings.resolved_chroma_dir}")


if __name__ == "__main__":
    main()
