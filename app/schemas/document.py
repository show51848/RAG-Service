from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentOut(BaseModel):
    """列出文件清單時回傳的完整資訊。"""
    id: int
    original_name: str
    status: DocumentStatus
    chunk_count: int
    created_at: datetime

    class Config:
        # from_attributes=True（舊版叫 orm_mode）讓 Pydantic 可以直接從
        # SQLAlchemy ORM 物件讀取屬性，不需要手動轉成 dict
        from_attributes = True


class DocumentSummary(BaseModel):
    """精簡版文件資訊，給 LLM tool calling 使用。

    只包含 LLM 需要的欄位（id + 名稱 + chunk 數），減少 token 消耗。
    """
    id: int
    original_name: str
    chunk_count: int

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    """上傳文件後的回應，告知客戶端文件 ID 與處理狀態。"""
    doc_id: int
    filename: str
    status: DocumentStatus
    # duplicate=True 表示這份文件之前已上傳過（內容相同），回傳既有文件的資訊
    duplicate: bool = False
