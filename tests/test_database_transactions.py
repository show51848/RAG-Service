import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User


def test_username_unique_constraint(postgres_session):
    """The database must reject two users with the same username."""
    postgres_session.add(User(username="alice", email="alice@example.com", hashed_password="x"))
    postgres_session.commit()

    postgres_session.add(User(username="alice", email="other@example.com", hashed_password="x"))
    with pytest.raises(IntegrityError):
        postgres_session.commit()


def test_email_unique_constraint(postgres_session):
    """The database must reject two users with the same email."""
    postgres_session.add(User(username="alice", email="alice@example.com", hashed_password="x"))
    postgres_session.commit()

    postgres_session.add(User(username="bob", email="alice@example.com", hashed_password="x"))
    with pytest.raises(IntegrityError):
        postgres_session.commit()


def test_session_can_be_reused_after_rollback(postgres_session):
    """After an integrity failure and rollback, the session remains usable."""
    postgres_session.add(User(username="alice", email="alice@example.com", hashed_password="x"))
    postgres_session.commit()

    postgres_session.add(User(username="alice", email="other@example.com", hashed_password="x"))
    with pytest.raises(IntegrityError):
        postgres_session.commit()

    # PostgreSQL 在 IntegrityError 後會把整個 transaction 標記為 aborted，
    # 在 rollback 之前這個 session 連 SELECT 都不能做——這跟 SQLite 的行為不同，
    # 也是這個測試要驗證的重點。
    postgres_session.rollback()

    postgres_session.add(User(username="bob", email="bob@example.com", hashed_password="x"))
    postgres_session.commit()

    assert postgres_session.query(User).count() == 2
