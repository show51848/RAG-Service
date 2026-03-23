from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentOut(BaseModel):
    id: int
    original_name: str
    status: DocumentStatus
    chunk_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentSummary(BaseModel):
    id: int
    original_name: str
    chunk_count: int

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    doc_id: int
    filename: str
    status: DocumentStatus
    duplicate: bool = False
