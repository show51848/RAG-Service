import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

# ── In-memory SQLite for tests ────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///./test_rag.db"
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def register(client: TestClient, username="alice", email="alice@example.com", password="secret"):
    return client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def login(client: TestClient, username="alice", password="secret"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_register_success(client):
    resp = register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert data["email"] == "alice@example.com"
    assert "id" in data


def test_register_duplicate_username(client):
    register(client)
    resp = register(client, email="other@example.com")  # same username
    assert resp.status_code == 409
    assert "alice" in resp.json()["detail"]


def test_register_duplicate_email(client):
    register(client)
    resp = register(client, username="bob")  # same email
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
    resp = login(client, username="nobody")
    assert resp.status_code == 401


def test_protected_route_without_token(client):
    resp = client.get("/docs")
    assert resp.status_code == 401


def test_protected_route_with_valid_token(client):
    register(client)
    token = login(client).json()["access_token"]
    resp = client.get("/docs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
