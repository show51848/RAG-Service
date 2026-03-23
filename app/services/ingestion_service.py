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
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        pages_text = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(pages_text)
        logger.info("Extracted %d characters from PDF (%d pages)", len(text), len(pages_text))
        return text

    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        logger.info("Read %d characters from TXT", len(text))
        return text

    else:
        raise ValueError(f"Unsupported file type: {ext}")


_CHINESE_HEADING = re.compile(r"^[一二三四五六七八九十百]+[、．.]")


def chunk_text(text: str) -> list[str]:
    """Split text into chunks by blank lines or Chinese section headings.

    A new chunk starts whenever:
    - A blank line separates paragraphs, OR
    - A line begins with a Chinese ordinal heading (一、二、三…)
    """
    if not text.strip():
        return []

    lines = text.splitlines()
    chunks: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        block = "\n".join(current_lines).strip()
        if block:
            chunks.append(block)
        current_lines.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Blank line → end of current paragraph
        if not line.strip():
            flush()
            i += 1
            continue

        # Chinese heading → start a new chunk even without blank line
        if _CHINESE_HEADING.match(line.strip()):
            flush()
            current_lines.append(line)
            i += 1
            continue

        current_lines.append(line)
        i += 1

    flush()

    logger.info("Created %d chunks (paragraph-based)", len(chunks))
    return chunks


def embed_and_index(
    chunks: list[str],
    doc_id: int,
    user_id: int,
    filename: str,
) -> None:
    """Batch-embed chunks and upsert into ChromaDB."""
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
    Full ingestion pipeline:
    1. Set status=processing
    2. Parse file → text
    3. Chunk text
    4. Embed & index to ChromaDB
    5. Set status=indexed
    On error: set status=failed with error_message
    """
    doc: Document | None = db.get(Document, doc_id)
    if doc is None:
        logger.error("Document id=%d not found", doc_id)
        return

    logger.info("Starting ingestion for doc_id=%d (%s)", doc_id, doc.original_name)
    doc.status = DocumentStatus.processing
    db.commit()

    try:
        # Step 1: Parse
        text = parse_file(doc.file_path)

        # Step 2: Chunk
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("No text content could be extracted from the file")

        # Step 3: Embed & index
        embed_and_index(
            chunks=chunks,
            doc_id=doc_id,
            user_id=doc.user_id,
            filename=doc.original_name,
        )

        # Step 4: Update status
        doc.status = DocumentStatus.indexed
        doc.chunk_count = len(chunks)
        db.commit()
        logger.info(
            "Ingestion complete for doc_id=%d: %d chunks indexed", doc_id, len(chunks)
        )

    except Exception as exc:
        logger.exception("Ingestion failed for doc_id=%d: %s", doc_id, exc)
        doc.status = DocumentStatus.failed
        doc.error_message = str(exc)
        db.commit()
