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
    client.post("/auth/register", json={"username": username, "email": email, "password": "pass"})
    resp = client.post("/auth/login", data={"username": username, "password": "pass"})
    return resp.json()["access_token"]


MOCK_CITATIONS = [
    Citation(doc_id=1, filename="guide.pdf", chunk="FastAPI is a modern web framework.", score=0.92),
]


def test_query_with_mock_openai(client):
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
    assert "沒有" in data["answer"] or len(data["answer"]) > 0


def test_query_doc_id_not_owned(client):
    """Querying with a doc_id belonging to another user should return 404."""
    token_a = _register_and_login(client, "alice", "alice@chat.com")
    token_b = _register_and_login(client, "bob", "bob@chat.com")

    # Create a doc as alice
    from app.models.document import Document, DocumentStatus
    from app.database import SessionLocal
    db = TestingSessionLocal()
    doc = Document(
        user_id=1,  # alice's id
        filename="alice.txt",
        original_name="alice.txt",
        file_path="/tmp/alice.txt",
        status=DocumentStatus.indexed,
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    resp = client.post(
        "/chat/query",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"question": "test", "doc_ids": [doc_id]},
    )
    assert resp.status_code == 404


def test_tools_calc(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    cases = [
        ("1+2*3", 7),
        ("(10 / 2) ** 2", 25.0),
        ("100 % 7", 2),
        ("10 // 3", 3),
    ]
    for expr, expected in cases:
        resp = client.post("/tools/calc", headers=headers, json={"expression": expr})
        assert resp.status_code == 200, f"Failed for: {expr}"
        data = resp.json()
        assert data["result"] == expected, f"Expected {expected} for '{expr}', got {data['result']}"


def test_tools_calc_invalid(client):
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
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/tools/docs", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
