import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    """Startup: create DB tables and ensure required directories exist."""
    logger.info("Starting up RAG Service...")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
    create_tables()
    logger.info("Database tables ready")
    logger.info("Upload dir: %s | Chroma dir: %s", settings.UPLOAD_DIR, settings.CHROMA_PERSIST_DIR)
    yield
    logger.info("Shutting down RAG Service")


app = FastAPI(
    title="RAG Service",
    description="AI document Q&A backend powered by ChromaDB + OpenAI",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(docs.router)
app.include_router(chat.router)
app.include_router(tools.router)


@app.get("/health", tags=["system"])
def health_check():
    """Service liveness probe."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse("/app/frontend/index.html")
