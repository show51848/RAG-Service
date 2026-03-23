from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    indexed = "indexed"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.pending, nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
