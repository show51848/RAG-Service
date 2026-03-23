from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_tables():
    from app.models import user, document  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_add_content_hash()


def _migrate_add_content_hash():
    """Add content_hash and file_hash columns to documents table if they don't exist (SQLite migration)."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(documents)"))
        columns = [row[1] for row in result.fetchall()]
        if "content_hash" not in columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)"))
        if "file_hash" not in columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN file_hash VARCHAR(32)"))
        conn.commit()
