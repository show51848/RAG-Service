from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./rag.db"
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ANTHROPIC_API_KEY: str = ""
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    UPLOAD_DIR: str = "./uploads"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
