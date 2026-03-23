from __future__ import annotations

import logging
from typing import Any

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "documents"


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
        )
        logger.info("ChromaDB PersistentClient initialised at %s", settings.CHROMA_PERSIST_DIR)
    return _client


def get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB collection '%s' ready", COLLECTION_NAME)
    return _collection


def upsert_chunks(
    chunks: list[str],
    embeddings: list[list[float]],
    doc_id: int,
    user_id: int,
    filename: str,
) -> None:
    """Upsert text chunks with their embeddings into the shared collection."""
    collection = get_collection()
    ids = [f"doc{doc_id}_chunk{i}" for i in range(len(chunks))]
    metadatas: list[dict[str, Any]] = [
        {
            "user_id": user_id,
            "doc_id": doc_id,
            "chunk_index": i,
            "filename": filename,
        }
        for i in range(len(chunks))
    ]
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )
    logger.info("Upserted %d chunks for doc_id=%d", len(chunks), doc_id)


def query_chunks(
    query_embedding: list[float],
    user_id: int,
    doc_ids: list[int] | None,
    top_k: int,
) -> dict[str, Any]:
    """Query the collection with metadata filters for user isolation."""
    collection = get_collection()

    where: dict[str, Any] = {"user_id": {"$eq": user_id}}

    if doc_ids:
        if len(doc_ids) == 1:
            where = {
                "$and": [
                    {"user_id": {"$eq": user_id}},
                    {"doc_id": {"$eq": doc_ids[0]}},
                ]
            }
        else:
            where = {
                "$and": [
                    {"user_id": {"$eq": user_id}},
                    {"doc_id": {"$in": doc_ids}},
                ]
            }

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return results


def delete_by_doc_id(doc_id: int) -> None:
    """Delete all chunks belonging to a document."""
    collection = get_collection()
    collection.delete(where={"doc_id": {"$eq": doc_id}})
    logger.info("Deleted all chunks for doc_id=%d", doc_id)
