# RAG Service

以 ChromaDB + Claude AI 為核心的文件問答後端，支援 JWT 認證、多用戶隔離、PDF/TXT 上傳與 Tool Calling。

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-orange)
![Claude](https://img.shields.io/badge/Anthropic-Claude_Haiku-blueviolet)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)

---

## Current Demo Stack

> This is a **single-container demo** optimised for quick local setup and portfolio review.
> See [Production Upgrade Path](#production-upgrade-path) below for what a real deployment would change.

| Layer | Demo choice | Why it's fine for demo |
|-------|-------------|------------------------|
| Database | PostgreSQL (Docker service) + Alembic migrations | Real RDBMS, FK/unique constraints enforced, `docker compose up` also runs migrations automatically. SQLite still works as a zero-setup fallback (`DATABASE_URL=sqlite:///./rag.db`) |
| Vector store | ChromaDB (embedded) | No extra service needed; data persisted in `chroma_data/` volume |
| Embedding | `all-MiniLM-L6-v2` via ONNX (local) | No API key, runs in-process, fast |
| LLM | Claude Haiku via Anthropic API | Cheap, fast, good enough for RAG responses |
| Task queue | Synchronous (inline ingestion) | Simplifies architecture; acceptable latency for small files |
| Auth | JWT / Argon2, single service | Stateless; no Redis session store needed at this scale |

---

## Production Upgrade Path

A production version of this service would replace or add:

```
Demo                          Production
─────────────────────────────────────────────────────────────
PostgreSQL (sync psycopg) →   PostgreSQL + async SQLAlchemy (asyncpg)
ChromaDB embedded        →    Qdrant / Pinecone (separate service)
Synchronous ingestion    →    Celery + Redis (async task queue)
Local file storage       →    S3-compatible object storage (boto3)
Single container         →    Kubernetes Deployment + HPA
Single-stage Dockerfile  →    Multi-stage build, non-root user
Secret in .env           →    AWS Secrets Manager / Vault
```

---

## 技術架構

```
┌─────────────────────────────────────────────────────┐
│               Browser / Client                       │
│           frontend/index.html  (SPA)                 │
└────────────────────┬────────────────────────────────┘
                     │ HTTP / JSON
┌────────────────────▼────────────────────────────────┐
│           FastAPI  (uvicorn, port 8000)               │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐    │
│  │  /auth   │  │  /docs   │  │ /chat  /tools   │    │
│  │ register │  │  upload  │  │ query   calc     │    │
│  │  login   │  │  list    │  │         docs     │    │
│  └────┬─────┘  └────┬─────┘  └───────┬─────────┘    │
│       │  JWT        │                │               │
│  ┌────▼─────────────▼────────────────▼────────────┐  │
│  │     PostgreSQL  (SQLAlchemy ORM + Alembic)       │  │
│  │    users · documents (status / hash / chunks)  │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────┐  ┌──────────────────────┐  │
│  │  ChromaDB (Vectors)  │  │  Anthropic Claude    │  │
│  │  chroma_data/ 持久化  │  │  claude-haiku-4-5    │  │
│  │  filter: user_id /   │  │  Answer generation   │  │
│  │          doc_id      │  └──────────────────────┘  │
│  └──────────────────────┘                            │
│  ┌──────────────────────┐                            │
│  │  all-MiniLM-L6-v2    │  ← local ONNX embedding   │
│  │  (runs in-process,   │    no external API needed  │
│  │   no API key)        │                            │
│  └──────────────────────┘                            │
└──────────────────────────────────────────────────────┘
              ▲  docker compose up
```

**請求流程（RAG 問答）**

```
上傳文件                              問答查詢
   │                                    │
   ▼                                    ▼
讀取 PDF/TXT                      Embed 問題
   │                              (all-MiniLM-L6-v2, local)
   ▼                                    │
分塊 (按語意段落切chunk)                 ▼
   │                              ChromaDB 向量搜尋
   ▼                              (user_id + doc_id filter)
Embed chunks                            │
(all-MiniLM-L6-v2, local ONNX)         ▼
   │                              取得 Top-K chunks
   ▼                                    │
ChromaDB Upsert                         ▼
(附 user_id / doc_id metadata)   Claude Haiku 生成答案
                                        │
                                        ▼
                                  回傳答案 + 引用來源
```

---

## 功能列表

| 功能 | 說明 |
|------|------|
| **JWT 認證** | Argon2 密碼雜湊、Bearer Token、60 分鐘過期 |
| **文件上傳** | PDF / TXT，MD5 去重，同步 ingestion pipeline |
| **RAG 問答** | 本機語意向量搜尋 → Claude Haiku 生成含引用編號答案 |
| **Tool Calling** | `/tools/calc` 安全運算式計算（AST，無 eval）；`/tools/docs` 文件摘要清單 |
| **多用戶隔離** | ChromaDB metadata filter 以 `user_id` 嚴格隔離，不可越權讀取 |
| **前端 SPA** | 純 HTML/CSS/JS，登入／註冊／上傳／問答一頁完成，零框架依賴 |
| **容器化** | 單一容器，`docker compose up` 即啟動，volume 持久化資料 |

---

## 快速啟動

### 前置需求

- Docker Desktop
- Anthropic API Key（[申請](https://console.anthropic.com/)）

### 1. 複製設定檔

```bash
cp .env.example .env
```

編輯 `.env`，填入必填欄位：

```env
# 必填：至少 32 字元，產生方式：openssl rand -hex 32
SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 必填：Anthropic API key
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

> **Fail-fast 設計**：`SECRET_KEY` 或 `ANTHROPIC_API_KEY` 未設定時，服務啟動即報錯退出，
> 不會用不安全的預設值默默跑起來。

### 2. 啟動服務

```bash
docker compose up --build
```

會一併啟動 PostgreSQL service，並在 `api` 容器啟動前自動執行 `alembic upgrade head`，不需要額外手動 migration。

### 3. 開啟網頁

瀏覽器前往 [http://localhost:8000](http://localhost:8000)

1. 點「註冊」建立帳號
2. 上傳 PDF 或 TXT 文件（等待狀態變為「已索引」）
3. 在問答欄輸入問題，獲得帶引用來源的 AI 回答

互動式 API 文件：[http://localhost:8000/api/docs](http://localhost:8000/api/docs)

### 4. 本機開發（不用 Docker）

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 安裝包含測試工具的開發依賴
pip install -r requirements-dev.txt

cp .env.example .env        # 填入 SECRET_KEY 和 ANTHROPIC_API_KEY
```

若本機有自己起的 PostgreSQL，先套用 migration 再啟動：

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

沒有 Postgres 也想跑起來，可以把 `.env` 的 `DATABASE_URL` 改成 `sqlite:///./rag.db`（零安裝，`create_tables()` 會自動建表）。

```bash
# 執行測試（不需要真實 API key，LLM 呼叫全部被 mock；
# 5 個 PostgreSQL 專屬測試需要本機有 Docker，沒有的話會 skip 而非 fail）
pytest tests/ -v
```

---

## API 端點

所有需要認證的端點請帶 Header：`Authorization: Bearer <token>`

### 認證

#### 註冊

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@example.com","password":"secret123"}'
# {"id":1,"username":"alice","email":"alice@example.com"}
```

#### 登入

```bash
curl -X POST http://localhost:8000/auth/login \
  -F "username=alice" -F "password=secret123"
# {"access_token":"eyJ...","token_type":"bearer"}
```

### 文件管理

#### 上傳文件

```bash
curl -X POST http://localhost:8000/docs/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf"
# {"doc_id":1,"filename":"report.pdf","status":"indexed"}
```

#### 列出文件

```bash
curl http://localhost:8000/docs \
  -H "Authorization: Bearer $TOKEN"
```

#### 刪除文件

```bash
curl -X DELETE http://localhost:8000/docs/1 \
  -H "Authorization: Bearer $TOKEN"
```

### RAG 問答

```bash
# 查詢全部文件
curl -X POST http://localhost:8000/chat/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"這份文件的主要結論是什麼？"}'

# 指定特定文件範圍
curl -X POST http://localhost:8000/chat/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"請摘要第一章","doc_ids":[1,2]}'
```

回應範例：

```json
{
  "answer": "根據文件 [1]，主要結論是...",
  "citations": [
    {"doc_id": 1, "filename": "report.pdf", "chunk": "...", "score": 0.89}
  ]
}
```

### Tools（Tool Calling 示範）

#### 安全數學計算

```bash
curl -X POST http://localhost:8000/tools/calc \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expression":"(10 / 2) ** 2 + 3 * 4"}'
# {"expression":"(10 / 2) ** 2 + 3 * 4","result":37.0}
```

#### 取得文件清單（供 LLM 呼叫）

```bash
curl http://localhost:8000/tools/docs \
  -H "Authorization: Bearer $TOKEN"
```

### 系統

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0"}
```

---

## 設計決策

### 為何用 ChromaDB？

- **嵌入式部署**：`PersistentClient` 直接寫入本機目錄，無需額外向量資料庫服務，單一容器搞定
- **原生 metadata filter**：內建 `where` 條件，天然契合多用戶隔離需求，不需應用層再做過濾
- **Python 原生**：與 FastAPI 同語言，無跨語言橋接，開發流暢
- **可升級性**：介面抽象在 `vectorstore/chroma_client.py`，日後換 Pinecone、Weaviate 只改此層

### 為何用 metadata filter 做用戶隔離？

傳統做法是每個用戶建立獨立 collection，但會造成 collection 數量線性增長。本專案改用**單一 `documents` collection + metadata filter**：

```python
# 寫入時標記擁有者
metadata = {"user_id": user_id, "doc_id": doc_id, "filename": filename}

# 查詢時嚴格過濾（不可能讀到他人資料）
where = {"$and": [{"user_id": user_id}, {"doc_id": {"$in": doc_ids}}]}

# 刪除時精確清除
collection.delete(where={"doc_id": doc_id})
```

### 為何計算工具用 AST 而非 eval？

`eval()` 允許任意 Python 執行，是嚴重安全漏洞。本專案自訂 AST 遍歷器，只允許白名單運算子（+、-、*、/、//、%、**），完全阻斷注入攻擊。

```python
# 攻擊者傳入惡意運算式
expression = "__import__('os').system('rm -rf /')"
eval(expression)   # 直接執行系統指令

# AST 白名單：Call 節點不在允許清單 → 直接拒絕，不執行
safe_eval(expression)  # ValueError: Unsupported AST node: Call
```

### 為何 Embedding 用本機模型而非 OpenAI API？

使用 `all-MiniLM-L6-v2`（透過 ChromaDB 內建的 ONNX Runtime 執行）：
- 不需要額外的 API key
- 無網路延遲，embedding 在本機完成
- 多語言短文本的向量品質已足夠 RAG 使用
- 降低每次上傳的費用（只有 LLM 生成答案才需要付費）

### Ingestion Pipeline

```
上傳檔案
  → MD5 去重（同用戶同檔案不重複索引）
  → PyMuPDF 解析 PDF / 純文字讀取
  → 按語意段落切塊（空白行或中文標題為切分點）
  → all-MiniLM-L6-v2 本機 Embedding
  → ChromaDB 存向量 + metadata（user_id / doc_id / filename）
```

---

## 專案結構

```
rag-service/
├── app/
│   ├── main.py              # FastAPI app、CORS（dev/prod 分離）、路由掛載
│   ├── config.py            # pydantic-settings，fail-fast 驗證
│   ├── database.py          # SQLAlchemy engine / session factory
│   ├── dependencies.py      # JWT 驗證 Depends
│   ├── models/              # SQLAlchemy ORM：User、Document
│   ├── schemas/             # Pydantic request/response schemas
│   ├── routers/             # auth / docs / chat / tools
│   ├── services/            # auth / embedding / ingestion / llm / retrieval
│   └── vectorstore/         # ChromaDB client 封裝
├── frontend/
│   └── index.html           # 單頁前端 SPA（零框架）
├── alembic/
│   ├── env.py                # migration 連線字串來源：app.config.settings
│   └── versions/              # migration 歷史
├── alembic.ini
├── tests/
│   ├── conftest.py          # 測試環境變數 + PostgreSQL testcontainers fixtures
│   ├── test_auth.py
│   ├── test_docs.py
│   ├── test_chat.py
│   ├── test_database_transactions.py    # unique constraint / rollback
│   └── test_postgresql_migrations.py    # alembic upgrade / FK 強制
├── Dockerfile               # 單階段 demo build；CMD 先跑 alembic upgrade head 再啟動 uvicorn
├── docker-compose.yml       # postgres + api 兩個 service
├── requirements.txt         # production 依賴（含 alembic、psycopg）
├── requirements-dev.txt     # -r requirements.txt + pytest + testcontainers
└── .env.example
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `SECRET_KEY` | **必填** | JWT 簽名金鑰，至少 32 字元；`openssl rand -hex 32` |
| `ANTHROPIC_API_KEY` | **必填** | Anthropic API 金鑰 |
| `APP_ENV` | `development` | `development` 或 `production`，影響 CORS 策略 |
| `ALLOWED_ORIGINS` | localhost 系列 | CORS 允許來源，production 請設為真實 domain |
| `DATABASE_URL` | `postgresql+psycopg://raguser:ragpassword@localhost:5432/ragdb` | SQLAlchemy 連線字串；本機零安裝可改 `sqlite:///./rag.db` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `raguser` / `ragpassword` / `ragdb` | 給 `docker-compose.yml` 的 postgres service 讀取 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT 過期時間（分鐘）|
| `TOP_K` | `5` | 向量搜尋回傳最大筆數 |
| `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB 持久化目錄 |
| `UPLOAD_DIR` | `./uploads` | 上傳檔案儲存目錄 |
