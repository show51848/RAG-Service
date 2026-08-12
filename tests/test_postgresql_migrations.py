import pathlib

import pytest
import sqlalchemy as sa
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.models.document import Document

ALEMBIC_INI = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"


def test_alembic_upgrade_creates_current_schema(postgres_container, postgres_engine):
    """Upgrading an empty PostgreSQL database creates all application tables."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_container.get_connection_url())

    upgrade(config, "head")
    try:
        tables = sa.inspect(postgres_engine).get_table_names()
        assert "users" in tables
        assert "documents" in tables
    finally:
        # 清乾淨，讓其他共用同一個 container 的測試不受影響
        downgrade(config, "base")


def test_postgresql_foreign_key_rejects_unknown_user(postgres_session):
    """PostgreSQL rejects a document whose user_id does not exist."""
    # SQLite 沒開 PRAGMA foreign_keys，這個錯誤在 SQLite 上會被靜默接受；
    # PostgreSQL 一律強制外鍵，這個測試就是要展示這個差異。
    postgres_session.add(
        Document(
            user_id=999999,
            filename="f.pdf",
            original_name="f.pdf",
            file_path="/tmp/f.pdf",
        )
    )
    with pytest.raises(IntegrityError):
        postgres_session.commit()
