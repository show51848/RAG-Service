from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import decode_jwt

# OAuth2PasswordBearer 告訴 FastAPI：從 Authorization: Bearer <token> 標頭取得 token
# tokenUrl 指向登入端點，Swagger UI 會用它來顯示「Authorize」按鈕
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db():
    """
    FastAPI Dependency：每個請求建立一個 DB Session，請求結束後一定關閉。
    用 try/finally 確保即使發生例外也能正確關閉，避免連線池洩漏。
    使用 yield 讓 FastAPI 能在請求處理完後繼續執行 finally 區塊。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI Dependency：驗證 JWT Token 並回傳對應的 User ORM 物件。

    設計成 Dependency 而非 middleware 的原因：
    - 可以只套用在需要認證的路由，不影響 /health、/auth/register 等公開端點
    - 可以組合其他 Dependency（例如 get_db），FastAPI 會自動處理依賴注入
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        # WWW-Authenticate 標頭是 OAuth2 規範要求的，告訴客戶端應用 Bearer scheme
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_jwt(token)
    if token_data.user_id is None:
        # decode_jwt 在 Token 無效時回傳空的 TokenData，而非直接拋出例外
        # 這樣可以統一在這裡處理錯誤回應格式
        raise credentials_exception

    # 用 db.get() 做 Primary Key 查詢，比 db.query().filter() 快
    # 因為 SQLAlchemy 會先查 identity map（session 快取），找不到才打 DB
    user = db.get(User, token_data.user_id)
    if user is None:
        # Token 合法但使用者已被刪除的情境
        raise credentials_exception
    return user
