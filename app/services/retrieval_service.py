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
    RAG 的「R」（Retrieval）：把問題向量化後，從 ChromaDB 找出最相關的文件片段。

    回傳每份文件的「最佳」片段（而非所有片段）的原因：
    同一份文件可能有多個 chunk 都很相關，但把它們全部傳給 LLM 會導致：
    1. Context window 被同一份文件占滿，其他文件的資訊被擠掉
    2. LLM 產出的引用標記變得混亂
    所以對每個 doc_id 只保留分數最高的一個 chunk。
    """
    if top_k is None:
        top_k = settings.TOP_K

    logger.info(
        "Retrieving top-%d chunks for user_id=%d, doc_ids=%s", top_k, user_id, doc_ids
    )

    # 把問題文字轉成向量，[0] 是因為 embed_texts 接受 list，我們只傳一個問題
    query_embedding = embed_texts([question])[0]

    results = query_chunks(
        query_embedding=query_embedding,
        user_id=user_id,
        doc_ids=doc_ids,
        top_k=top_k,
    )

    # ChromaDB query 回傳的格式是 {"documents": [[...]], "metadatas": [[...]], "distances": [[...]]}
    # 第一層 list 對應多個 query（我們只傳一個），所以取 [0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    # 每個 doc_id 只保留分數最高的 chunk，避免同一文件占用太多 context
    best: dict[int, Citation] = {}
    for doc_text, meta, distance in zip(documents, metadatas, distances):
        # ChromaDB cosine distance 範圍：0（完全相同）到 2（完全相反）
        # 轉換成 0~1 的相似度分數：score = 1 - distance/2
        score = round(1 - distance / 2, 4)
        doc_id = int(meta["doc_id"])
        if doc_id not in best or score > best[doc_id].score:
            best[doc_id] = Citation(
                doc_id=doc_id,
                filename=meta["filename"],
                chunk=doc_text,
                score=score,
            )

    # 依相似度分數從高到低排序，讓 LLM 先看到最相關的資料
    citations = sorted(best.values(), key=lambda c: c.score, reverse=True)
    logger.info("Retrieved %d citations (after doc_id dedup)", len(citations))
    return citations
