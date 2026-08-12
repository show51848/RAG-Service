import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

# 測試用獨立資料庫，避免污染正式資料
TEST_DATABASE_URL = "sqlite:///./test_docs.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    """每個測試前後重建資料表，確保測試隔離。"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    # 綁定/還原限定在這個 fixture 的生命週期內，避免跟其他測試檔的
    # app.dependency_overrides[get_db] 互相覆蓋（pytest 收集整個 tests/
    # 目錄時會 import 全部檔案，模組層級的全域賦值會被後 import 的檔案蓋掉）
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _register_and_login(client: TestClient, username="alice", email="alice@test.com"):
    """輔助函式：快速完成註冊 + 登入，回傳 JWT Token。"""
    client.post("/auth/register", json={"username": username, "email": email, "password": "pass"})
    resp = client.post("/auth/login", data={"username": username, "password": "pass"})
    return resp.json()["access_token"]


# 重複使用相同內容（50 次重複），確保有足夠的文字能被切成多個 chunks
FAKE_TXT_CONTENT = b"This is a test document. " * 50


def _make_ingest_mock():
    """
    建立一個模擬 ingest 的 patch。

    為何要 mock ingest：
    1. 測試文件 API 邏輯（上傳、列表、刪除），不需要真正執行 embedding
    2. 避免在 CI 環境中依賴 ONNX 模型下載或外部 API
    3. 加速測試執行（embedding 可能需要幾秒）

    fake_ingest 會把 status 改為 indexed，讓後續的斷言可以正確運作。
    """
    from app.models.document import DocumentStatus

    def fake_ingest(doc_id, db):
        from app.models.document import Document
        doc = db.get(Document, doc_id)
        if doc:
            doc.status = DocumentStatus.indexed
            doc.chunk_count = 5
            db.commit()

    return patch("app.routers.docs.ingest", side_effect=fake_ingest)


def test_upload_txt(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    with _make_ingest_mock():
        resp = client.post(
            "/docs/upload",
            headers=headers,
            # files= 對應 multipart/form-data 格式，(filename, file_object, content_type)
            files={"file": ("test.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.txt"
    assert data["status"] == "indexed"


def test_upload_pdf(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    # 使用假的 PDF bytes（真正的 PDF 解析被 mock 掉了，所以不需要有效的 PDF 結構）
    mock_pdf = b"%PDF-1.4 fake pdf content"
    with _make_ingest_mock():
        resp = client.post(
            "/docs/upload",
            headers=headers,
            files={"file": ("report.pdf", io.BytesIO(mock_pdf), "application/pdf")},
        )
    assert resp.status_code == 201
    assert resp.json()["filename"] == "report.pdf"


def test_upload_unsupported_type(client):
    """上傳不支援的檔案類型（CSV）應該回傳 415 Unsupported Media Type。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/docs/upload",
        headers=headers,
        files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
    )
    assert resp.status_code == 415


def test_list_docs(client):
    """上傳一份文件後，列表應該回傳 1 筆資料。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    with _make_ingest_mock():
        client.post(
            "/docs/upload",
            headers=headers,
            files={"file": ("a.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    resp = client.get("/docs", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_docs_isolation(client):
    """使用者 A 的文件列表不應該出現使用者 B 的文件（資料隔離測試）。"""
    token_a = _register_and_login(client, "alice", "alice@test.com")
    token_b = _register_and_login(client, "bob", "bob@test.com")

    # Alice 上傳一份文件
    with _make_ingest_mock():
        client.post(
            "/docs/upload",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("alice.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )

    # Bob 查詢文件列表應該看不到 Alice 的文件
    resp_b = client.get("/docs", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.json() == []


def test_delete_doc(client):
    """上傳後刪除，文件列表應該變空。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    with _make_ingest_mock():
        upload_resp = client.post(
            "/docs/upload",
            headers=headers,
            files={"file": ("del.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    doc_id = upload_resp.json()["doc_id"]

    # mock delete_by_doc_id 避免真正去清 ChromaDB（測試環境可能沒有資料）
    with patch("app.routers.docs.delete_by_doc_id"):
        del_resp = client.delete(f"/docs/{doc_id}", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/docs", headers=headers)
    assert list_resp.json() == []


def test_delete_other_user_doc(client):
    """使用者 B 嘗試刪除使用者 A 的文件應該回傳 404（而非 403）。

    回傳 404 而非 403 的原因：不向攻擊者透露該資源存在，避免資源列舉攻擊。
    """
    token_a = _register_and_login(client, "alice", "alice@test.com")
    token_b = _register_and_login(client, "bob", "bob@test.com")

    with _make_ingest_mock():
        upload = client.post(
            "/docs/upload",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("a.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    doc_id = upload.json()["doc_id"]

    with patch("app.routers.docs.delete_by_doc_id"):
        resp = client.delete(f"/docs/{doc_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404
