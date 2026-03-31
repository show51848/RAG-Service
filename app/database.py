from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# create_engine 建立資料庫連線池
# SQLite 預設只允許同一個執行緒存取，check_same_thread=False 讓 FastAPI 的
# 非同步請求可以共用連線；PostgreSQL 不需要這個參數
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

# autocommit=False：每次操作需明確呼叫 db.commit()，確保交易完整性
# autoflush=False：避免在 commit 前意外觸發 flush 產生 SQL
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 所有 ORM Model 都要繼承這個 Base，
# SQLAlchemy 才能知道哪些 class 對應資料庫的哪些表
class Base(DeclarativeBase):
    pass


def create_tables():
    # 必須 import model 模組，Base.metadata 才能收集到這些 Table 的定義
    # noqa: F401 告訴 linter 這些看似「未使用」的 import 是刻意的
    from app.models import user, document  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # SQLAlchemy 的 create_all 只能建立新表，無法自動新增欄位
    # 因此手動執行遷移腳本補上後來新增的欄位
    _migrate_add_content_hash()


def _migrate_add_content_hash():
    """Add content_hash and file_hash columns to documents table if they don't exist (SQLite migration).

    SQLite 不支援 ALTER TABLE DROP COLUMN / 重新命名，且 SQLAlchemy 沒有內建
    migration（Alembic 才有）。MVP 階段直接用 PRAGMA 查欄位再補 ALTER 最簡單。
    """
    with engine.connect() as conn:
        # PRAGMA table_info 回傳每欄的 (cid, name, type, notnull, dflt_value, pk)
        result = conn.execute(text("PRAGMA table_info(documents)"))
        columns = [row[1] for row in result.fetchall()]

        # 只在欄位不存在時才執行 ALTER，讓這個函式可以安全地重複呼叫
        if "content_hash" not in columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)"))
        if "file_hash" not in columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN file_hash VARCHAR(32)"))
        conn.commit()
