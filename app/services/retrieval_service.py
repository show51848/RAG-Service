import logging

from app.config import settings
from app.schemas.chat import Citation
from app.services.embedding_service import embed_texts
from app.vectorstore.chroma_client import query_chunks

logger = logging.getLogger(__name__)


def retrieve(
    user_id: int,
    question: str,
    doc_ids: list[int] | None = None,
    top_k: int | None = None,
) -> list[Citation]:
    """
    Embed the question and query ChromaDB for the most relevant chunks.
    Returns a list of Citation objects sorted by relevance score (ascending distance = higher similarity).
    """
    if top_k is None:
        top_k = settings.TOP_K

    logger.info(
        "Retrieving top-%d chunks for user_id=%d, doc_ids=%s", top_k, user_id, doc_ids
    )

    query_embedding = embed_texts([question])[0]

    results = query_chunks(
        query_embedding=query_embedding,
        user_id=user_id,
        doc_ids=doc_ids,
        top_k=top_k,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    # Build per-doc_id best citation (highest score = lowest distance)
    best: dict[int, Citation] = {}
    for doc_text, meta, distance in zip(documents, metadatas, distances):
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity score 0–1
        score = round(1 - distance / 2, 4)
        doc_id = int(meta["doc_id"])
        if doc_id not in best or score > best[doc_id].score:
            best[doc_id] = Citation(
                doc_id=doc_id,
                filename=meta["filename"],
                chunk=doc_text,
                score=score,
            )

    citations = sorted(best.values(), key=lambda c: c.score, reverse=True)
    logger.info("Retrieved %d citations (after doc_id dedup)", len(citations))
    return citations
