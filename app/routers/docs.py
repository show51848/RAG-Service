import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.schemas.document import DocumentOut, UploadResponse
from app.services.ingestion_service import ingest
from app.vectorstore.chroma_client import delete_by_doc_id

router = APIRouter(prefix="/docs", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for indexing",
)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    """
    Upload a PDF or TXT file. The file is saved to disk, then synchronously
    parsed, chunked, embedded, and indexed into ChromaDB.

    - **file**: PDF or TXT file (multipart/form-data)
    """
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{ext}' is not supported. Allowed: {ALLOWED_EXTENSIONS}",
        )

    # Read content and compute hashes
    content = file.file.read()
    file_hash = hashlib.md5(content).hexdigest()
    content_hash = hashlib.sha256(content).hexdigest()

    # Check if the same file has already been indexed by this user (MD5 dedup)
    existing = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.file_hash == file_hash,
            Document.status == DocumentStatus.indexed,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "文件已存在", "doc_id": existing.id},
        )

    # Ensure user upload directory exists
    user_upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id)
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename to avoid collisions
    unique_filename = f"{uuid.uuid4().hex}_{original_name}"
    file_path = user_upload_dir / unique_filename

    # Save file to disk
    with open(file_path, "wb") as f:
        f.write(content)

    # Create DB record
    doc = Document(
        user_id=current_user.id,
        filename=unique_filename,
        original_name=original_name,
        file_path=str(file_path),
        content_hash=content_hash,
        file_hash=file_hash,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Synchronous ingestion (MVP)
    ingest(doc_id=doc.id, db=db)
    db.refresh(doc)

    return UploadResponse(doc_id=doc.id, filename=doc.original_name, status=doc.status)


@router.get(
    "",
    response_model=list[DocumentOut],
    summary="List all documents for the current user",
)
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    """
    Return all documents uploaded by the authenticated user,
    including their indexing status and chunk count.
    """
    docs = db.query(Document).filter(Document.user_id == current_user.id).all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its indexed data",
)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Permanently delete a document:
    1. Verify ownership
    2. Remove vectors from ChromaDB
    3. Delete the raw file from disk
    4. Remove the DB record
    """
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {doc_id} not found",
        )

    # Delete vectors
    delete_by_doc_id(doc_id)

    # Delete file from disk
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # Delete DB record
    db.delete(doc)
    db.commit()
