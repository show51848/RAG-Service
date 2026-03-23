import logging

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

_ef = None


def get_embedding_function() -> DefaultEmbeddingFunction:
    global _ef
    if _ef is None:
        logger.info("Loading DefaultEmbeddingFunction (all-MiniLM-L6-v2, ONNX)")
        _ef = DefaultEmbeddingFunction()
    return _ef


def embed_texts(texts: list[str]) -> list[list[float]]:
    ef = get_embedding_function()
    return [[float(x) for x in v] for v in ef(texts)]
