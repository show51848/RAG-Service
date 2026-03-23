from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import decode_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db():
    """Yield a SQLAlchemy session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decode JWT and return the authenticated User, or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = decode_jwt(token)
    if token_data.user_id is None:
        raise credentials_exception

    user = db.get(User, token_data.user_id)
    if user is None:
        raise credentials_exception
    return user
