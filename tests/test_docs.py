import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///./test_docs.db"
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


def _register_and_login(client: TestClient, username="alice", email="alice@test.com"):
    client.post("/auth/register", json={"username": username, "email": email, "password": "pass"})
    resp = client.post("/auth/login", data={"username": username, "password": "pass"})
    return resp.json()["access_token"]


FAKE_TXT_CONTENT = b"This is a test document. " * 50


def _make_ingest_mock():
    """Return a patch that short-circuits ingestion by marking doc as indexed."""
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
            files={"file": ("test.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.txt"
    assert data["status"] == "indexed"


def test_upload_pdf(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    # Minimal valid PDF bytes
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
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/docs/upload",
        headers=headers,
        files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
    )
    assert resp.status_code == 415


def test_list_docs(client):
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
    """User A must not see User B's documents."""
    token_a = _register_and_login(client, "alice", "alice@test.com")
    token_b = _register_and_login(client, "bob", "bob@test.com")

    with _make_ingest_mock():
        client.post(
            "/docs/upload",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("alice.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )

    resp_b = client.get("/docs", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.json() == []


def test_delete_doc(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    with _make_ingest_mock():
        upload_resp = client.post(
            "/docs/upload",
            headers=headers,
            files={"file": ("del.txt", io.BytesIO(FAKE_TXT_CONTENT), "text/plain")},
        )
    doc_id = upload_resp.json()["doc_id"]

    with patch("app.routers.docs.delete_by_doc_id"):
        del_resp = client.delete(f"/docs/{doc_id}", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/docs", headers=headers)
    assert list_resp.json() == []


def test_delete_other_user_doc(client):
    """User B cannot delete User A's document."""
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
