import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app
from app.schemas.chat import Citation

TEST_DATABASE_URL = "sqlite:///./test_chat.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, username="alice", email="alice@chat.com"):
    """輔助函式：快速完成註冊 + 登入，回傳 JWT Token。"""
    client.post("/auth/register", json={"username": username, "email": email, "password": "pass"})
    resp = client.post("/auth/login", data={"username": username, "password": "pass"})
    return resp.json()["access_token"]


# 預先定義好模擬的 Citation 資料，測試中重複使用
MOCK_CITATIONS = [
    Citation(doc_id=1, filename="guide.pdf", chunk="FastAPI is a modern web framework.", score=0.92),
]


def test_query_with_mock_openai(client):
    """
    測試 RAG 查詢的完整 HTTP 介面。

    同時 mock retrieve 和 generate_answer 的原因：
    1. 避免依賴 ChromaDB 向量資料庫（測試環境可能沒有資料）
    2. 避免真正呼叫 Anthropic API（需要 API key 且有費用）
    3. 讓測試聚焦在「路由層是否正確組裝回應」而非「LLM 是否回答正確」
    """
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch("app.routers.chat.retrieve", return_value=MOCK_CITATIONS),
        patch(
            "app.routers.chat.generate_answer",
            return_value=("FastAPI 是一個現代的 Web 框架。[1]", MOCK_CITATIONS),
        ),
    ):
        resp = client.post(
            "/chat/query",
            headers=headers,
            json={"question": "What is FastAPI?"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert len(data["citations"]) == 1
    assert data["citations"][0]["doc_id"] == 1
    assert data["citations"][0]["score"] == 0.92


def test_query_empty_docs(client):
    """當沒有找到相關文件時，應該回傳 200 但 citations 為空列表。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch("app.routers.chat.retrieve", return_value=[]),
        patch(
            "app.routers.chat.generate_answer",
            return_value=("目前沒有找到相關文件片段。", []),
        ),
    ):
        resp = client.post(
            "/chat/query",
            headers=headers,
            json={"question": "What is FastAPI?"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["citations"] == []
    # 確保有回傳說明訊息（不是空字串）
    assert "沒有" in data["answer"] or len(data["answer"]) > 0


def test_query_doc_id_not_owned(client):
    """
    使用者 B 用 doc_ids 指定使用者 A 的文件進行查詢，應該回傳 404。

    這個測試驗證「使用者只能查詢自己的文件」的安全邊界。
    """
    token_a = _register_and_login(client, "alice", "alice@chat.com")
    token_b = _register_and_login(client, "bob", "bob@chat.com")

    # 直接在測試資料庫中建立 Alice 的文件記錄（繞過上傳 API）
    from app.models.document import Document, DocumentStatus
    from app.database import SessionLocal
    db = TestingSessionLocal()
    doc = Document(
        user_id=1,  # alice's id（第一個註冊的使用者 ID 為 1）
        filename="alice.txt",
        original_name="alice.txt",
        file_path="/tmp/alice.txt",
        status=DocumentStatus.indexed,
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    # Bob 嘗試查詢 Alice 的文件，應該得到 404
    resp = client.post(
        "/chat/query",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"question": "test", "doc_ids": [doc_id]},
    )
    assert resp.status_code == 404


def test_tools_calc(client):
    """驗證計算機端點能正確計算各種數學運算式。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    cases = [
        ("1+2*3", 7),          # 運算子優先順序：乘法先於加法
        ("(10 / 2) ** 2", 25.0),  # 括號與次方
        ("100 % 7", 2),         # 取餘數
        ("10 // 3", 3),          # 整數除法
    ]
    for expr, expected in cases:
        resp = client.post("/tools/calc", headers=headers, json={"expression": expr})
        assert resp.status_code == 200, f"Failed for: {expr}"
        data = resp.json()
        assert data["result"] == expected, f"Expected {expected} for '{expr}', got {data['result']}"


def test_tools_calc_invalid(client):
    """
    驗證計算機端點能正確拒絕危險或無效的運算式。

    測試案例說明：
    - __import__('os').system('ls')：嘗試執行系統指令（安全漏洞測試）
    - open('/etc/passwd')：嘗試讀取系統檔案（安全漏洞測試）
    - 1/0：除以零
    - abc + 1：變數名稱不被允許（只支援數字常數）
    """
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    invalid_cases = [
        "__import__('os').system('ls')",
        "open('/etc/passwd')",
        "1/0",
        "abc + 1",
    ]
    for expr in invalid_cases:
        resp = client.post("/tools/calc", headers=headers, json={"expression": expr})
        assert resp.status_code == 422, f"Expected 422 for dangerous expr: {expr}"


def test_tools_docs(client):
    """工具文件列表端點應該回傳 200 和陣列（即使是空的）。"""
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/tools/docs", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
