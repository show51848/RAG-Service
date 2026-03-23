from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.schemas.auth import TokenData

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_jwt(user_id: int, username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_jwt(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        username = payload.get("username")
        if user_id is None:
            raise JWTError("Missing subject")
        return TokenData(user_id=int(user_id), username=username)
    except JWTError:
        return TokenData()
