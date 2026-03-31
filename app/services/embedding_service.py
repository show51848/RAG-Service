import logging

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

# 模組層級的單例：第一次呼叫時才載入模型（lazy loading），
# 之後重複使用同一個實例，避免每次請求都重新載入耗費大量時間和記憶體
_ef = None


def get_embedding_function() -> DefaultEmbeddingFunction:
    """
    取得（或初始化）ChromaDB 的預設 Embedding Function。

    DefaultEmbeddingFunction 使用 all-MiniLM-L6-v2 模型（透過 ONNX Runtime），
    選擇這個模型的原因：
    - 完全在本機執行，不需要 OpenAI API key 或網路連線
    - 模型小（約 23MB），啟動快，效能在多語言短文本上仍然夠用
    - ChromaDB 官方支援，版本相容性有保障
    """
    global _ef
    if _ef is None:
        logger.info("Loading DefaultEmbeddingFunction (all-MiniLM-L6-v2, ONNX)")
        _ef = DefaultEmbeddingFunction()
    return _ef


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    將文字列表轉換成向量（浮點數列表的列表）。

    float() 轉換是必要的：ONNX 輸出的是 numpy.float32，
    ChromaDB 和 JSON 序列化都需要 Python 原生的 float。
    """
    ef = get_embedding_function()
    return [[float(x) for x in v] for v in ef(texts)]
