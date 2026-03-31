# pydantic-settings 自動從環境變數或 .env 讀取設定，並在 process 啟動時做型別驗證
# 若必填欄位缺失，pydantic 會在 Settings() 呼叫時立即拋出 ValidationError（fail-fast）
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 環境識別 ──────────────────────────────────────────────────────────────
    # 用於在 main.py 切換 CORS 策略等環境相關行為
    # Literal 讓 pydantic 在 APP_ENV 設錯值時直接報錯，而非默默接受
    APP_ENV: Literal["development", "production"] = "development"

    # ── 資料庫 ────────────────────────────────────────────────────────────────
    # SQLite 供本機開發；production 請換成 postgresql+asyncpg://...
    DATABASE_URL: str = "sqlite:///./rag.db"

    # ── JWT 認證 ──────────────────────────────────────────────────────────────
    # 無預設值 → 未設定時 pydantic 直接報錯，不會用不安全的值靜默啟動
    # 產生方式：openssl rand -hex 32
    SECRET_KEY: str

    # HS256 是對稱式演算法，單服務足夠；多服務共用驗證才需要換成 RS256
    ALGORITHM: str = "HS256"

    # Token 60 分鐘後過期，限制被竊 token 的有效窗口
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── 外部 API ──────────────────────────────────────────────────────────────
    # 無預設值 → 未設定時啟動直接報錯，而非在第一次呼叫 LLM 才炸
    ANTHROPIC_API_KEY: str

    # ── 向量資料庫 ────────────────────────────────────────────────────────────
    # ChromaDB 本地持久化目錄；production 可換成 Qdrant / Pinecone 等獨立服務
    CHROMA_PERSIST_DIR: str = "./chroma_data"

    # ── 檔案上傳 ──────────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"

    # ── RAG 參數 ──────────────────────────────────────────────────────────────
    # 向量搜尋回傳的最多候選段落數，越大越慢但涵蓋更廣
    TOP_K: int = 5

    # ── CORS ──────────────────────────────────────────────────────────────────
    # 預設只含本機開發常用 port；production 請透過環境變數覆寫：
    # ALLOWED_ORIGINS='["https://your-domain.com"]'
    # pydantic-settings 支援將 JSON 陣列字串自動解析為 list[str]
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_strength(cls, v: str) -> str:
        """拒絕過短的 key，強迫使用者真的設定安全值。"""
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters. "
                "Generate one with:  openssl rand -hex 32"
            )
        return v

    @field_validator("ANTHROPIC_API_KEY")
    @classmethod
    def anthropic_key_not_empty(cls, v: str) -> str:
        """空字串意味著忘記設定，直接在啟動時告知，而非等到第一次 LLM 呼叫才報錯。"""
        if not v.strip():
            raise ValueError(
                "ANTHROPIC_API_KEY must not be empty. "
                "Set it in your .env file or environment."
            )
        return v

    @model_validator(mode="after")
    def warn_localhost_in_production(self) -> "Settings":
        """在 production 模式下，若 ALLOWED_ORIGINS 仍只有 localhost，視為設定疏漏。"""
        if self.APP_ENV == "production":
            localhost_only = all(
                "localhost" in o or "127.0.0.1" in o
                for o in self.ALLOWED_ORIGINS
            )
            if localhost_only:
                raise ValueError(
                    "APP_ENV=production but ALLOWED_ORIGINS only contains localhost. "
                    "Set ALLOWED_ORIGINS to your production domain(s)."
                )
        return self

    class Config:
        # 優先讀取 .env 檔；若環境變數已存在則以環境變數為準
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全域單例：整個應用程式共用，避免重複解析設定
# Settings() 在此處就會觸發所有 validator — 設定有問題則 process 立即退出
settings = Settings()
