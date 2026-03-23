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
    Perform a RAG query:
    1. Optionally filter by specific doc_ids (must belong to the current user)
    2. Embed the question and retrieve top-K relevant chunks
    3. Generate an answer via gpt-4o-mini with citations

    - **question**: the natural-language question to answer
    - **doc_ids**: optional list of document IDs to restrict the search scope
    """
    # Validate doc_ids ownership
    if body.doc_ids:
        for did in body.doc_ids:
            doc = db.get(Document, did)
            if doc is None or doc.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document {did} not found",
                )

    citations = retrieve(
        user_id=current_user.id,
        question=body.question,
        doc_ids=body.doc_ids,
    )
    answer, used_citations = generate_answer(question=body.question, citations=citations)

    return QueryResponse(answer=answer, citations=used_citations)
