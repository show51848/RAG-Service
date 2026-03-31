from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.chat import QueryRequest, QueryResponse
from app.services.llm_service import generate_answer
from app.services.retrieval_service import retrieve

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask a question against the user's document knowledge base",
)
def query(
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """
    RAG 完整查詢流程：
    1. 若有指定 doc_ids，驗證這些文件確實屬於當前使用者
    2. 將問題向量化並從 ChromaDB 找出最相關的段落（Retrieval）
    3. 將段落和問題傳給 Claude，生成帶引用的答案（Generation）

    為何在路由層做 doc_ids 的所有權驗證（而非在 retrieval_service）：
    - retrieval_service 只知道向量查詢，不應該依賴 SQLAlchemy Session
    - 路由層已經有 db session，適合做業務規則驗證
    - 讓服務層保持純粹，方便測試時 mock
    """
    # 驗證 doc_ids 所有權：確保使用者不能查詢不屬於自己的文件
    if body.doc_ids:
        for did in body.doc_ids:
            doc = db.get(Document, did)
            if doc is None or doc.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document {did} not found",
                )

    # 向量搜尋：把問題轉成 embedding，找出最相關的文件片段
    citations = retrieve(
        user_id=current_user.id,
        question=body.question,
        doc_ids=body.doc_ids,
    )

    # 生成答案：把找到的片段和問題交給 LLM
    answer, used_citations = generate_answer(question=body.question, citations=citations)

    return QueryResponse(answer=answer, citations=used_citations)
