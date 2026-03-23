from pydantic import BaseModel


class Citation(BaseModel):
    doc_id: int
    filename: str
    chunk: str
    score: float


class QueryRequest(BaseModel):
    question: str
    doc_ids: list[int] | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]


class CalcRequest(BaseModel):
    expression: str


class CalcResponse(BaseModel):
    expression: str
    result: float | int
