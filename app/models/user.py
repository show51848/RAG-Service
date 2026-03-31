from datetime import datetime

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

    # default=datetime.utcnow（不加括號）：每次新增記錄時才呼叫函式，
    # 若寫成 default=datetime.utcnow()（加括號）會在 class 載入時固定成同一個時間
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
