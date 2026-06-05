from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.schemas.auth import TokenData

# CryptContext 讓我們可以同時支援多種雜湊演算法，並在升級時自動重新雜湊
# argon2 是目前密碼雜湊的最佳實踐（比 bcrypt 更抗 GPU 暴力破解）
# deprecated="auto" 讓舊版演算法的雜湊在使用者下次登入時自動升級
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    # passlib 會自動加入 salt，不需要手動處理
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # 用 constant-time 比較，防止 timing attack
    return pwd_context.verify(plain_password, hashed_password)


def create_jwt(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),   # JWT 標準欄位，subject = 使用者識別碼
        "username": username,   # 自訂欄位，方便 log 顯示而不需查 DB
        "exp": expire,          # JWT 標準欄位，python-jose 會自動驗證過期時間
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_jwt(token: str) -> TokenData:
    """
    解碼並驗證 JWT Token。

    回傳空的 TokenData（而非拋出例外）的原因：
    讓 dependencies.py 中的 get_current_user 統一決定要回傳哪種 HTTP 錯誤，
    保持錯誤處理邏輯集中在一處。
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        username = payload.get("username")
        if user_id is None:
            raise JWTError("Missing subject")
        return TokenData(user_id=int(user_id), username=username)
    except JWTError:
        # Token 過期、簽名錯誤、格式錯誤都會進到這裡，統一回傳空物件
        return TokenData()
