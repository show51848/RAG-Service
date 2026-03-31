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

# 允許的檔案副檔名白名單，拒絕所有其他格式
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

    MVP 階段使用同步處理（非 Celery/BackgroundTasks）的原因：
    - 簡化架構，不需要 Redis broker 和 worker 進程
    - 文件通常在幾秒內處理完，對 MVP 使用者體驗可接受
    """
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{ext}' is not supported. Allowed: {ALLOWED_EXTENSIONS}",
        )

    # 一次讀入記憶體，方便計算雜湊值（避免讀兩次檔案）
    content = file.file.read()

    # MD5 用於快速去重：速度快，碰撞率在實務上可接受
    # SHA-256 用於精確內容比對（如需要）
    file_hash = hashlib.md5(content).hexdigest()
    content_hash = hashlib.sha256(content).hexdigest()

    # 同一使用者上傳相同檔案時（MD5 相同且已成功索引），直接拒絕
    # 避免浪費儲存空間和 embedding 運算資源
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

    # 每個使用者的檔案存在獨立子目錄，避免不同使用者的同名檔案互相覆蓋
    user_upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id)
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    # UUID 前綴確保即使同一使用者上傳兩份同名檔案也不會衝突
    unique_filename = f"{uuid.uuid4().hex}_{original_name}"
    file_path = user_upload_dir / unique_filename

    # 先存檔，再建 DB 記錄（若存檔失敗就不會有孤立的 DB 記錄）
    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        user_id=current_user.id,
        filename=unique_filename,
        original_name=original_name,
        file_path=str(file_path),
        content_hash=content_hash,
        file_hash=file_hash,
        status=DocumentStatus.pending,  # ingest() 會把狀態改為 processing → indexed
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 同步執行 ingestion pipeline
    ingest(doc_id=doc.id, db=db)

    # refresh 取得 ingest() 更新後的最新狀態（indexed 或 failed）
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

    只回傳當前使用者的文件（user_id 過濾），確保使用者看不到其他人的文件。
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
    1. Verify ownership（防止使用者刪除別人的文件）
    2. Remove vectors from ChromaDB
    3. Delete the raw file from disk
    4. Remove the DB record

    刪除順序：先刪 ChromaDB 和磁碟，最後才刪 DB 記錄。
    若順序反過來（先刪 DB）且中途失敗，就會出現有向量資料但沒有 DB 記錄的孤兒資料。
    """
    doc = db.get(Document, doc_id)

    # 同時檢查文件存在且屬於當前使用者，兩個條件失敗都回傳 404
    # 刻意不區分「不存在」和「不屬於你」，避免讓攻擊者得知哪些 ID 存在
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {doc_id} not found",
        )

    # 從 ChromaDB 刪除所有相關向量
    delete_by_doc_id(doc_id)

    # 從磁碟刪除原始檔案（若還存在的話）
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # 最後刪除資料庫記錄
    db.delete(doc)
    db.commit()
