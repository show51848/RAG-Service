from __future__ import annotations

import logging
from typing import Any

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)

# 模組層級的單例，確保整個應用程式只有一個 ChromaDB 連線實例
# 避免重複開啟相同的持久化目錄導致資料損壞
_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None

# 所有文件的 chunks 都存在同一個 collection 裡，用 metadata 過濾使用者資料
# 這比每個使用者一個 collection 更好管理，且 ChromaDB 支援 metadata 篩選
COLLECTION_NAME = "documents"


def get_chroma_client() -> chromadb.PersistentClient:
    """Lazy-init ChromaDB client，第一次呼叫時才建立連線。"""
    global _client
    if _client is None:
        # PersistentClient 把向量資料持久化到磁碟，重啟服務後資料仍在
        # 開發時也可用 chromadb.Client()（純記憶體），但資料不會保留
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
        )
        logger.info("ChromaDB PersistentClient initialised at %s", settings.CHROMA_PERSIST_DIR)
    return _client


def get_collection() -> chromadb.Collection:
    """取得（或建立）文件向量 collection，並指定使用 cosine 相似度。"""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        # get_or_create_collection：idempotent，不論 collection 是否存在都安全呼叫
        # hnsw:space=cosine：使用餘弦相似度而非預設的 L2 距離
        # 餘弦相似度對文字向量更合適，因為它衡量方向（語意）而非絕對距離
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
    """Upsert text chunks with their embeddings into the shared collection.

    使用 upsert 而非 insert 的原因：
    當使用者重新上傳同名文件時，upsert 會更新現有向量而非新增重複資料。
    ID 格式 doc{doc_id}_chunk{i} 確保每個 chunk 有全局唯一的識別碼。
    """
    collection = get_collection()
    ids = [f"doc{doc_id}_chunk{i}" for i in range(len(chunks))]
    metadatas: list[dict[str, Any]] = [
        {
            "user_id": user_id,   # 用於查詢時的使用者隔離過濾
            "doc_id": doc_id,     # 用於按文件過濾或刪除
            "chunk_index": i,     # chunk 在原文中的順序，方便排序或顯示
            "filename": filename, # 直接存在 metadata 裡，查詢時不需回頭查 DB
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
    """Query the collection with metadata filters for user isolation.

    user_id 過濾是資料隔離的關鍵：確保使用者 A 的問題永遠不會搜尋到使用者 B 的文件。
    ChromaDB 的 where 語法類似 MongoDB，支援 $eq、$in、$and 等邏輯運算子。
    """
    collection = get_collection()

    # 預設只過濾 user_id，搜尋該使用者的所有文件
    where: dict[str, Any] = {"user_id": {"$eq": user_id}}

    if doc_ids:
        # ChromaDB 的限制：$and 內只能有「欄位過濾」，不能直接加 $or
        # 單一 doc_id 用 $eq，多個 doc_id 用 $in，兩者都要同時滿足 user_id 條件
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
        query_embeddings=[query_embedding],  # list of lists，支援批次查詢
        n_results=top_k,
        where=where,
        # 明確指定需要的欄位，避免回傳不必要的資料（例如 embeddings 向量很大）
        include=["documents", "metadatas", "distances"],
    )
    return results


def delete_by_doc_id(doc_id: int) -> None:
    """Delete all chunks belonging to a document.

    刪除文件時必須同步從 ChromaDB 刪除向量，否則：
    1. 佔用磁碟空間
    2. 已刪除文件的內容可能出現在其他使用者的搜尋結果中（若 doc_id 被重用）
    """
    collection = get_collection()
    collection.delete(where={"doc_id": {"$eq": doc_id}})
    logger.info("Deleted all chunks for doc_id=%d", doc_id)
