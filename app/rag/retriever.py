"""
ChromaDB retrieval for the RAG pipeline.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction


def get_collection(persist_dir: str, model_name: str) -> chromadb.Collection:
    """
    Open the existing ChromaDB collection.

    Raises FileNotFoundError if the collection has not been ingested yet.
    """
    if not Path(persist_dir).exists():
        raise FileNotFoundError(
            f"ChromaDB store not found at '{persist_dir}'. "
            "Run  python scripts/ingest_rag.py  first."
        )

    ef = SentenceTransformerEmbeddingFunction(model_name=model_name)
    client = chromadb.PersistentClient(path=persist_dir)

    try:
        return client.get_collection(name="soldiers", embedding_function=ef)
    except Exception as exc:
        raise FileNotFoundError(
            f"Collection 'soldiers' not found in '{persist_dir}'. "
            "Run  python scripts/ingest_rag.py  first."
        ) from exc


def retrieve(
    query: str,
    k: int,
    persist_dir: str,
    model_name: str,
) -> list[dict]:
    """
    Query the vector store and return the top-k results.

    Each result dict has keys:
        text       — the original text chunk
        metadata   — dict with nom, prenom, regiment, ark_url, source_image, …
        distance   — float similarity distance (lower = closer)
    """
    collection = get_collection(persist_dir, model_name)
    results = collection.query(
        query_texts=[query],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict] = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({"text": text, "metadata": meta, "distance": dist})

    return chunks
