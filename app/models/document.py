from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# str 繼承讓 Enum 成員的值是字串，存入 DB 和序列化為 JSON 時都不需額外轉換
class DocumentStatus(str, PyEnum):
    pending = "pending"       # 剛上傳，尚未開始處理
    processing = "processing" # 正在解析 / 切片 / 向量化
    indexed = "indexed"       # 已完成索引，可以被查詢
    failed = "failed"         # 處理過程中發生錯誤


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ForeignKey 確保每份文件一定屬於某個存在的使用者
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # filename：儲存在磁碟上的實際檔名（含 uuid 前綴，避免同名衝突）
    # original_name：使用者上傳時的原始檔名，顯示給使用者看
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_name: Mapped[str] = mapped_column(String, nullable=False)

    # 絕對路徑，方便 ingestion service 直接開啟檔案
    file_path: Mapped[str] = mapped_column(String, nullable=False)

    # 用 SQLAlchemy Enum 型別讓資料庫也知道合法值，提供額外的資料完整性保護
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.pending, nullable=False
    )

    # content_hash (SHA-256)：文件內容的雜湊，可用於精確比對內容是否相同
    # file_hash (MD5)：快速去重用，MD5 碰撞率極低，速度比 SHA-256 快
    # index=True：讓按雜湊值查詢重複文件的速度更快
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # 發生錯誤時記錄原因，方便 debug
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # 切成幾個 chunk，讓使用者知道文件被分成多少段落進行索引
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # onupdate：每次 UPDATE 時自動更新時間戳，不需要應用層手動維護
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
