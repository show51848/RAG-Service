# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 開發工作流程

每一個功能或修改，**依序**完成以下四個階段，不可跳步：

1. **構思 & 規劃** — 說明做法、影響範圍、邊界條件，等待使用者確認後才動工
2. **測試骨架** — 先寫 `tests/` 下的測試結構（函式名稱、docstring、`pass` 或 `pytest.mark.skip`），確定測試涵蓋面
3. **實作** — 完成功能程式碼，使測試可以執行
4. **驗證** — 執行 `pytest` 全部綠燈才算完成；若有失敗，修復後重跑，不留紅燈交付

```
構思規劃 → 等確認 → 測試骨架 → 實作 → pytest 全綠 ✓
```

---

## 常用指令

```bash
# 安裝依賴（開發 + 測試）
pip install -r requirements-dev.txt

# 啟動開發伺服器（需要先設定環境變數）
uvicorn app.main:app --reload

# 執行所有測試
pytest tests/ -v

# 執行單一測試檔
pytest tests/test_auth.py -v

# 執行單一測試函式
pytest tests/test_auth.py::test_register_success -v

# 產生新的 migration（改動 models/ 後）
alembic revision --autogenerate -m "說明這次改了什麼"

# 套用 migration 到目前的 DATABASE_URL
alembic upgrade head
```

Swagger UI 在 `/api/docs`（非 `/docs`，避免與前端路由衝突）。

---

## 環境變數設定

必填（缺少任一項，應用程式啟動時立即報錯）：

```bash
SECRET_KEY=<至少 32 字元>   # openssl rand -hex 32
ANTHROPIC_API_KEY=<sk-ant-...>
```

選填（有預設值）：

```
APP_ENV=development          # development | production
DATABASE_URL=postgresql+psycopg://raguser:ragpassword@localhost:5432/ragdb
POSTGRES_USER=raguser        # 給 docker-compose 的 postgres service 用
POSTGRES_PASSWORD=ragpassword
POSTGRES_DB=ragdb
CHROMA_PERSIST_DIR=./chroma_data
UPLOAD_DIR=./uploads
TOP_K=5
ALLOWED_ORIGINS=["http://localhost:3000"]
```

本機沒有 Docker/Postgres 時，可將 `DATABASE_URL` 覆寫為 `sqlite:///./rag.db` 做零安裝開發。

測試時 `tests/conftest.py` 會自動設定假的 key，不需要真實值。

---

## 架構分層職責

```
routers/       HTTP 層：驗證請求格式、呼叫 service、回傳 schema
services/      業務邏輯：orchestration、錯誤處理、資料流
vectorstore/   向量存取層：封裝 ChromaDB 操作
models/        SQLAlchemy ORM 模型
schemas/       Pydantic 輸入輸出定義
dependencies/  FastAPI 依賴注入（auth、db session）
```

**原則：**
- Router 不直接碰資料庫或向量庫，一律透過 service
- Service 不回傳 ORM 物件給 router，一律用 schema
- 跨層資料傳遞用 Pydantic schema，不傳 dict

---

## 關鍵架構決策

**ChromaDB：單一 collection + metadata 過濾**
所有使用者的 chunks 都存在同一個 `"documents"` collection（非每人一個 collection），以 `user_id` metadata field 做隔離過濾。chunk ID 格式：`doc{doc_id}_chunk{i}`。

**Embedding：本機執行，不需 API key**
使用 ChromaDB 內建的 `DefaultEmbeddingFunction`，底層是 `all-MiniLM-L6-v2`（ONNX Runtime）。第一次呼叫時下載並快取模型（約 23MB）。

**LLM：Claude Haiku**
`claude-haiku-4-5-20251001`，用於 RAG 回答生成。回答語言固定為繁體中文，並要求引用格式 `[數字]`。

**文字切分：段落式，非固定長度**
以空白行或中文序號標題（一、二、三…）為切分點，保留語意完整性。不使用固定長度 + overlap 的方式。

**Ingestion：同步處理**
MVP 階段 `POST /docs/upload` 同步完成解析 → 切分 → embedding → ChromaDB 寫入，不使用 Celery/BackgroundTasks。

**資料庫：PostgreSQL + Alembic（SQLite 為本機開發 fallback）**
`create_tables()`（`app/database.py`）依 engine dialect 分流：
- PostgreSQL：schema 完全交給 Alembic（`alembic/versions/`）管理，`create_tables()` 對它是 no-op。Docker 啟動時 `Dockerfile` 的 `CMD` 會先執行 `alembic upgrade head` 再啟動 uvicorn；非 Docker 的本機 Postgres 需自行先跑 `alembic upgrade head`。
- SQLite：維持原本零設定的開發體驗，`create_tables()` 呼叫 `Base.metadata.create_all()`，並保留 `_migrate_add_content_hash()`（用 `PRAGMA table_info` 檢查並補 `ALTER TABLE`）處理新欄位。

新增/修改 model 後，用 `alembic revision --autogenerate` 產生 migration，**務必人工檢查**產出內容再套用——尤其 `Document.status` 用的 `Enum(DocumentStatus)` 在 Postgres 上會建立 native `ENUM` type（`documentstatus`），autogenerate 的 `downgrade()` 不會自動把它一併砍掉，需要手動補上 `sa.Enum(...).drop(op.get_bind(), checkfirst=True)`。

**檔案儲存路徑**：`uploads/{user_id}/{uuid}_{original_filename}`

---

## API 路由摘要

| 路由 | 說明 |
|------|------|
| `POST /auth/register` | 註冊 |
| `POST /auth/login` | 登入，回傳 JWT |
| `POST /docs/upload` | 上傳 PDF/TXT，同步完成索引 |
| `GET /docs` | 列出當前使用者的文件 |
| `DELETE /docs/{id}` | 刪除文件（同步清理 ChromaDB + 磁碟） |
| `POST /chat/query` | RAG 查詢（可指定 `doc_ids` 限定文件範圍） |
| `POST /tools/calc` | 安全數學運算（AST-based，供 LLM tool calling 用） |
| `GET /tools/docs` | 精簡版文件列表（供 LLM 決定要查詢哪個 doc_id） |

---

## user_id 隔離

- 所有向量存取、文件查詢、embedding 操作**必須帶入 `user_id`**
- ChromaDB 以 `where: {"user_id": {"$eq": user_id}}` 過濾，確保跨使用者隔離
- API endpoint 的 `user_id` 一律從 JWT token 取得（`current_user` dependency），**不接受 client 傳入**
- 刪除文件時回傳 404 而不區分「不存在」與「不屬於你」，避免 enumeration 攻擊

---

## 安全規則

- **禁止使用 `eval()`、`exec()`**；`/tools/calc` 使用 `ast.parse(mode="eval")` + AST 白名單運算子
- SQL 操作一律透過 SQLAlchemy ORM 或 parameterized query，禁止字串拼接 SQL
- 上傳檔案驗證：副檔名白名單（`.pdf`、`.txt`）+ 重複上傳以 MD5 去重
- Secret 只從環境變數讀取；`SECRET_KEY` 長度不足 32 字元時 pydantic validator 直接拒絕啟動

---

## 測試慣例

- 測試檔放在 `tests/`，命名 `test_<feature>.py`
- Fixture 定義在 `tests/conftest.py`
- 使用 `httpx.AsyncClient` + `pytest-asyncio` 做整合測試
- 大部分測試（auth/docs/chat）用獨立的 SQLite **檔案**資料庫（非 in-memory——TestClient 和
  SQLAlchemy session 可能不在同一條連線，in-memory SQLite 的連線隔離會讓兩者看不到彼此的資料），
  向量庫用獨立 chroma client（`EphemeralClient`）
- `test_postgresql_migrations.py`、`test_database_transactions.py` 驗證 PostgreSQL 專屬行為
  （FK 強制、unique constraint、rollback 後 session 是否還能用），透過 `tests/conftest.py` 的
  `postgres_container`/`postgres_session` fixture 用 testcontainers 自動起一個暫時 Postgres；
  本機沒有 Docker 時這組測試會 `skip` 而非 `fail`，不影響 `pytest tests/ -v` 全綠
- 每個測試後清理狀態，不依賴執行順序

---

## 程式碼風格

- 不加不必要的 docstring 或 comment；邏輯自明時不需解釋
- 不做預防性的 error handling（針對不可能發生的情境）
- 不提前抽象：三行重複才考慮抽函式，一次性邏輯直接寫
- Type hint 跟著現有程式碼風格走，不在未修改的地方補標注
