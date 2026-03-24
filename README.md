# RAG Service

以 ChromaDB + Claude AI 為核心的文件問答後端，支援 JWT 認證、多用戶隔離、PDF/TXT 上傳與 Tool Calling。

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-orange)
![Claude](https://img.shields.io/badge/Anthropic-Claude_Haiku-blueviolet)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)

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
│  │          SQLite  (SQLAlchemy ORM)               │  │
│  │    users · documents (status / hash / chunks)  │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────┐  ┌──────────────────────┐  │
│  │  ChromaDB (Vectors)  │  │  Anthropic Claude    │  │
│  │  chroma_data/ 持久化  │  │  claude-haiku-4-5    │  │
│  │  filter: user_id /   │  │  Embedding + LLM     │  │
│  │          doc_id      │  └──────────────────────┘  │
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
   │                                    │
   ▼                                    ▼
分塊 (按照語意切chunk)    ChromaDB 向量搜尋
   │                              (user_id + doc_id filter)
   ▼                                    │
Anthropic Embedding                     ▼
   │                              取得 Top-K chunks
   ▼                                    │
ChromaDB Upsert                         ▼
(附 user_id / doc_id metadata)   Claude claude-haiku-4-5 生成答案
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
| **RAG 問答** | 語意向量搜尋 → Claude Haiku 生成含引用編號答案 |
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

編輯 `.env`：

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
SECRET_KEY=your-secret-key          # openssl rand -hex 32
DATABASE_URL=sqlite:////app/data/rag.db
```

### 2. 啟動服務

```bash
docker compose up --build
```

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
pip install -r requirements.txt
cp .env.example .env        # 填入 ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

```bash
pytest tests/ -v            # 執行測試
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

優點：架構簡單、管理容易、隔離由 ChromaDB 查詢層保證。

### 為何計算工具用 AST 而非 eval？

`eval()` 允許任意 Python 執行，是嚴重安全漏洞。本專案自訂 AST 遍歷器，只允許白名單運算子（+、-、*、/、//、%、**），完全阻斷注入攻擊。

### Ingestion Pipeline

```
上傳檔案
  → MD5 去重（同用戶同檔案不重複索引）
  → PyMuPDF 解析 PDF / 純文字讀取
  → 固定大小分塊（size=500, overlap=50）
  → Anthropic Embedding API
  → ChromaDB 存向量 + metadata（user_id / doc_id / filename）
```

---

## 專案結構

```
rag-service/
├── app/
│   ├── main.py              # FastAPI app、CORS、路由掛載、lifespan
│   ├── config.py            # pydantic-settings 環境變數
│   ├── database.py          # SQLAlchemy engine / session factory
│   ├── dependencies.py      # JWT 驗證 Depends
│   ├── models/              # SQLAlchemy ORM：User、Document
│   ├── schemas/             # Pydantic request/response schemas
│   ├── routers/             # auth / docs / chat / tools
│   ├── services/            # auth / embedding / ingestion / llm / retrieval
│   └── vectorstore/         # ChromaDB client 封裝
├── frontend/
│   └── index.html           # 單頁前端 SPA（零框架）
├── tests/                   # pytest 整合測試
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | **必填** | Anthropic API 金鑰 |
| `SECRET_KEY` | `change-me` | JWT 簽名金鑰，正式環境請用 `openssl rand -hex 32` |
| `DATABASE_URL` | `sqlite:///./rag.db` | SQLAlchemy 連線字串 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT 過期時間（分鐘）|
| `CHUNK_SIZE` | `500` | 文件切塊大小（字元數）|
| `CHUNK_OVERLAP` | `50` | 相鄰切塊重疊大小 |
| `TOP_K` | `5` | 向量搜尋回傳最大筆數 |
