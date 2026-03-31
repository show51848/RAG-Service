# schemas 是 Pydantic 模型，負責 API 層的資料驗證與序列化
# 與 SQLAlchemy ORM model 分開，避免把資料庫結構暴露給 API 呼叫者
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    username: str
    # EmailStr 會驗證 email 格式，不合法時自動回傳 422 Unprocessable Entity
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    id: int
    username: str
    email: str
    # 刻意不包含 hashed_password，確保密碼雜湊值不會出現在 API 回應裡


class LoginResponse(BaseModel):
    access_token: str
    # token_type 固定為 "bearer"，是 OAuth2 規範要求的欄位
    token_type: str = "bearer"


class TokenData(BaseModel):
    """JWT 解碼後的 payload 資料，在 dependencies.py 中用來識別使用者。

    欄位都允許 None：當 Token 無效時，decode_jwt 會回傳空的 TokenData，
    而不是拋出例外，讓呼叫端統一決定如何處理錯誤。
    """
    user_id: int | None = None
    username: str | None = None
