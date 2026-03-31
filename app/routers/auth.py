from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.schemas.auth import LoginResponse, RegisterRequest, RegisterResponse
from app.services.auth_service import create_jwt, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """
    Create a new user account.

    - **username**: unique display name
    - **email**: unique email address
    - **password**: plain-text password (hashed with argon2 before storage)
    """
    # 應用層也做唯一性檢查，原因：資料庫的 unique constraint 拋出的例外
    # 不容易產生友善的錯誤訊息，這裡先查詢可以給出具體的 409 說明
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken",
        )
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),  # 永遠不儲存明文密碼
    )
    db.add(user)
    db.commit()
    # db.refresh(user) 從資料庫重新載入，取得資料庫自動產生的 id
    db.refresh(user)
    return RegisterResponse(id=user.id, username=user.username, email=user.email)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and obtain a JWT token",
)
def login(
    # OAuth2PasswordRequestForm 是 FastAPI 內建的表單解析器，
    # 遵從 OAuth2 規範，接受 application/x-www-form-urlencoded 格式
    # （不是 JSON），這樣 Swagger UI 的 "Authorize" 按鈕才能直接使用
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate with username and password.

    Returns a Bearer JWT token valid for the configured expiry duration.
    """
    user = db.query(User).filter(User.username == form_data.username).first()

    # 刻意把「使用者不存在」和「密碼錯誤」合併成同一個錯誤訊息
    # 分開說明會讓攻擊者知道哪些帳號存在（user enumeration attack）
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_jwt(user_id=user.id, username=user.username)
    return LoginResponse(access_token=token, token_type="bearer")
