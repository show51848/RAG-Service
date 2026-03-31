import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.database import create_tables
from app.routers import auth, chat, docs, tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan：取代舊版 @app.on_event("startup/shutdown")。
    yield 前為啟動邏輯，yield 後為關閉清理。
    """
    logger.info("Starting up RAG Service (env=%s)...", settings.APP_ENV)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
    create_tables()
    logger.info("Database tables ready")
    logger.info("Upload dir: %s | Chroma dir: %s", settings.UPLOAD_DIR, settings.CHROMA_PERSIST_DIR)
    yield
    logger.info("Shutting down RAG Service")


app = FastAPI(
    title="RAG Service",
    description="AI document Q&A backend powered by ChromaDB + Claude",
    version="1.0.0",
    lifespan=lifespan,
    # 移到 /api/docs 避免與前端 /docs 路由衝突
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── CORS 策略：dev / prod 分開 ────────────────────────────────────────────────
#
# Development：
#   - 在 settings.ALLOWED_ORIGINS（預設 localhost 系列）基礎上額外允許 "null"
#   - "null" 是讓直接用 file:// 開啟 index.html 的請求也能通過
#   - methods / headers 全開，方便本機用 curl 或 Swagger 測試
#
# Production：
#   - 只允許 settings.ALLOWED_ORIGINS（必須在 .env 明確設定為真實 domain）
#   - methods / headers 收斂為實際用到的值，減少攻擊面
#   - "null" 不加入，避免任何本機檔案協議繞過 CORS

if settings.APP_ENV == "development":
    cors_origins = list(settings.ALLOWED_ORIGINS) + ["null"]
    cors_methods = ["*"]
    cors_headers = ["*"]
else:
    cors_origins = list(settings.ALLOWED_ORIGINS)
    # 只開放本服務實際使用的 HTTP 方法與標頭
    cors_methods = ["GET", "POST", "DELETE", "OPTIONS"]
    cors_headers = ["Authorization", "Content-Type"]

logger.info("CORS origins: %s", cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=cors_methods,
    allow_headers=cors_headers,
)

app.include_router(auth.router)   # /auth/register, /auth/login
app.include_router(docs.router)   # /docs/upload, /docs, /docs/{id}
app.include_router(chat.router)   # /chat/query
app.include_router(tools.router)  # /tools/calc, /tools/docs


@app.get("/health", tags=["system"])
def health_check():
    """Service liveness probe — 供 Docker / k8s 健康檢查使用。"""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def serve_frontend():
    # SPA 入口；include_in_schema=False 讓此路由不出現在 Swagger 文件
    return FileResponse("/app/frontend/index.html")
