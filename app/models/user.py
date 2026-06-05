from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    # primary_key + autoincrement：讓資料庫自動產生唯一 ID，不需應用層管理
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # unique=True 在資料庫層強制唯一性，搭配應用層的重複檢查提供雙重保障
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # 只儲存雜湊值，永遠不儲存明文密碼
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
