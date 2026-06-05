import logging
import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import Document, DocumentStatus
from app.services.embedding_service import embed_texts
from app.vectorstore.chroma_client import upsert_chunks

logger = logging.getLogger(__name__)


def parse_file(file_path: str) -> str:
    """Extract plain text from PDF or TXT file."""
    ext = Path(file_path).suffix.lower()
    logger.info("Parsing file: %s (ext=%s)", file_path, ext)

    if ext == ".pdf":
        # PyMuPDF (fitz) 支援複雜排版，比 pdfminer 更快
        # 延遲 import 是因為並非所有檔案都是 PDF，避免不必要的載入時間
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        pages_text = [page.get_text() for page in doc]
        doc.close()
        # 用換行符合併各頁文字，保留頁面間的段落感
        text = "\n".join(pages_text)
        logger.info("Extracted %d characters from PDF (%d pages)", len(text), len(pages_text))
        return text

    elif ext == ".txt":
        # errors="replace" 讓非 UTF-8 字元用 ? 取代，而非拋出例外
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        logger.info("Read %d characters from TXT", len(text))
        return text

    else:
        raise ValueError(f"Unsupported file type: {ext}")


# 預編譯正則表達式：比在迴圈內每次重新編譯效能更好
# 匹配中文序號開頭的段落標題，例如「一、前言」「二．說明」
_CHINESE_HEADING = re.compile(r"^[一二三四五六七八九十百]+[、．.]")
MAX_CHUNK_CHARS = 1000  # 單一 chunk 字元上限，避免超長段落塞爆 LLM context

def chunk_text(text: str) -> list[str]:
    """Split text into chunks by blank lines or Chinese section headings.

    A new chunk starts whenever:
    - A blank line separates paragraphs, OR
    - A line begins with a Chinese ordinal heading (一、二、三…)

    選擇段落切分而非固定長度切分的原因：
    - 保留語意完整性，避免把同一個句子切斷
    - 中文文件的段落通常在合理長度範圍內
    - 固定長度切分需要調整 overlap 參數，增加複雜度
    """
    if not text.strip():
        return []

    lines = text.splitlines()
    chunks: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        """把目前累積的行組成一個 chunk 並清空暫存區。"""
        block = "\n".join(current_lines).strip()
        if block:
            if len(block) > MAX_CHUNK_CHARS:
                block = block[:MAX_CHUNK_CHARS]
            chunks.append(block)
        current_lines.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        # 空白行代表段落結束，把目前的段落存起來
        if not line.strip():
            flush()
            i += 1
            continue

        # 遇到中文標題就強制切段，即使前面沒有空白行
        # 這讓每個章節都是獨立的 chunk，查詢結果更精準
        if _CHINESE_HEADING.match(line.strip()):
            flush()
            current_lines.append(line)
            i += 1
            continue

        current_lines.append(line)
        i += 1

    # 處理最後一段（沒有空白行結尾的情況）
    flush()

    logger.info("Created %d chunks (paragraph-based)", len(chunks))
    return chunks


def embed_and_index(
    chunks: list[str],
    doc_id: int,
    user_id: int,
    filename: str,
) -> None:
    """Batch-embed chunks and upsert into ChromaDB.

    一次傳入所有 chunks 而非逐個 embed 的原因：
    ONNX batch 處理比逐一呼叫快很多，可充分利用 SIMD 向量化計算。
    """
    logger.info("Embedding %d chunks for doc_id=%d", len(chunks), doc_id)

    embeddings = embed_texts(chunks)
    logger.info("Generated %d embeddings locally", len(embeddings))

    upsert_chunks(
        chunks=chunks,
        embeddings=embeddings,
        doc_id=doc_id,
        user_id=user_id,
        filename=filename,
    )


def ingest(doc_id: int, db: Session) -> None:
    """
    完整的文件索引流程：
    1. 設定 status=processing（讓前端可以顯示處理中）
    2. 解析檔案取得純文字
    3. 將文字切成段落 chunks
    4. 批次 embed 並寫入 ChromaDB
    5. 設定 status=indexed

    發生任何錯誤時：設定 status=failed 並記錄錯誤訊息，
    而非讓例外向上傳播導致 HTTP 500，讓使用者可以看到失敗原因。
    """
    doc: Document | None = db.get(Document, doc_id)
    if doc is None:
        logger.error("Document id=%d not found", doc_id)
        return

    logger.info("Starting ingestion for doc_id=%d (%s)", doc_id, doc.original_name)

    # 立即更新狀態並 commit，讓其他請求能即時看到「處理中」狀態
    doc.status = DocumentStatus.processing
    db.commit()

    try:
        # Step 1: 解析原始檔案
        text = parse_file(doc.file_path)

        # Step 2: 切成段落
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("No text content could be extracted from the file")

        # Step 3: 向量化並寫入 ChromaDB
        embed_and_index(
            chunks=chunks,
            doc_id=doc_id,
            user_id=doc.user_id,
            filename=doc.original_name,
        )

        # Step 4: 更新 DB 狀態為成功
        doc.status = DocumentStatus.indexed
        doc.chunk_count = len(chunks)
        db.commit()
        logger.info(
            "Ingestion complete for doc_id=%d: %d chunks indexed", doc_id, len(chunks)
        )

    except Exception as exc:
        # 捕捉所有例外：解析錯誤、IO 錯誤、ChromaDB 錯誤都統一在此處理
        logger.exception("Ingestion failed for doc_id=%d: %s", doc_id, exc)
        doc.status = DocumentStatus.failed
        doc.error_message = str(exc)
        db.commit()
