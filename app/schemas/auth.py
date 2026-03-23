from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    id: int
    username: str
    email: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int | None = None
    username: str | None = None
