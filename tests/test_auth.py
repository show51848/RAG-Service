import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

# ── 測試用資料庫設定 ──────────────────────────────────────────────────────────
# 使用獨立的 SQLite 檔案而非記憶體（:memory:）原因：
# FastAPI TestClient 和 SQLAlchemy session 可能在不同連線中，
# 記憶體 SQLite 的連線隔離會讓兩者看不到彼此的資料
TEST_DATABASE_URL = "sqlite:///./test_rag.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """取代正式環境的 get_db，讓測試使用獨立的 SQLite 資料庫。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    """每個測試前建立資料表，測試後刪除，確保測試之間完全隔離。

    autouse=True 表示所有測試都自動套用這個 fixture，不需要明確宣告。
    """
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """每個測試取得一個新的 TestClient 實例。

    dependency override 的綁定/還原限定在這個 fixture 的生命週期內，避免跟
    其他測試檔的 app.dependency_overrides[get_db] 互相覆蓋（pytest 收集整個
    tests/ 目錄時會 import 全部檔案，模組層級的全域賦值會被後 import 的檔案蓋掉）。
    """
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ── 輔助函式（避免在每個測試中重複 HTTP 請求程式碼）────────────────────────

def register(client: TestClient, username="alice", email="alice@example.com", password="secret"):
    return client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def login(client: TestClient, username="alice", password="secret"):
    # 注意：login 用 data=（form-encoded），不是 json=（JSON body）
    # 因為 /auth/login 遵從 OAuth2 規範，接受 multipart form
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )


# ── 測試案例 ──────────────────────────────────────────────────────────────────

def test_register_success(client):
    resp = register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert data["email"] == "alice@example.com"
    assert "id" in data  # 確保 DB 有自動產生 ID


def test_register_duplicate_username(client):
    register(client)
    # 相同 username 但不同 email 應該回傳 409
    resp = register(client, email="other@example.com")
    assert resp.status_code == 409
    assert "alice" in resp.json()["detail"]  # 錯誤訊息要說明是哪個 username 衝突


def test_register_duplicate_email(client):
    register(client)
    # 相同 email 但不同 username 應該回傳 409
    resp = register(client, username="bob")
    assert resp.status_code == 409


def test_login_success(client):
    register(client)
    resp = login(client)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    register(client)
    resp = login(client, password="wrongpass")
    assert resp.status_code == 401


def test_login_unknown_user(client):
    # 未註冊的使用者登入應該回傳 401（而非 404）
    # 避免 user enumeration：不應告知使用者「此帳號不存在」
    resp = login(client, username="nobody")
    assert resp.status_code == 401


def test_protected_route_without_token(client):
    # 未帶 Token 存取受保護端點應該回傳 401
    resp = client.get("/docs")
    assert resp.status_code == 401


def test_protected_route_with_valid_token(client):
    register(client)
    token = login(client).json()["access_token"]
    # 帶有合法 Token 應該可以存取受保護端點
    resp = client.get("/docs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
