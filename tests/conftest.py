"""
Root test configuration.

這個 conftest.py 必須在 os.environ 設定後，app 模組才被 import。
pytest 保證 conftest.py 先於 test_*.py 載入，所以在此處設定環境變數
可以確保 Settings() 實例化時看得到這些值。

原因：config.py 的 SECRET_KEY 和 ANTHROPIC_API_KEY 已移除預設值，
啟動時若未設定就會 fail-fast。測試環境不需要真實的 key（LLM 呼叫全部被
mock 掉），但 pydantic 的 validator 仍然需要值存在且格式合法。
"""
import os

# 在任何 app 模組被 import 之前設定測試用環境變數
# setdefault 確保若使用者已在 shell 設定了真實 key，不會被覆蓋
os.environ.setdefault("SECRET_KEY", "pytest-secret-key-for-testing-only-min32!!")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real-just-for-pytest")
os.environ.setdefault("APP_ENV", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base

# ── PostgreSQL testcontainers fixtures ───────────────────────────────────────
# 給 tests/test_postgresql_migrations.py 和 tests/test_database_transactions.py
# 共用：測試執行時自動起一個暫時的真 Postgres container，不需要事先手動
# docker-compose up。本機沒有 Docker 時整組測試會被 skip（而非 fail），
# 讓 pytest tests/ -v 在沒有 Docker 的機器上仍然全綠。


@pytest.fixture(scope="session")
def postgres_container():
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker not available: {exc}")

    yield container
    container.stop()


@pytest.fixture(scope="session")
def postgres_engine(postgres_container):
    return create_engine(postgres_container.get_connection_url())


@pytest.fixture
def postgres_session(postgres_engine):
    """每個測試前建表、測後清表，跟 test_auth.py/test_docs.py 的 create_all/drop_all 慣例一致。"""
    Base.metadata.create_all(bind=postgres_engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=postgres_engine)
