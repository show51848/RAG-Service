from pydantic import BaseModel


class Citation(BaseModel):
    """代表一個從 ChromaDB 取回的文件片段及其相關資訊。

    用於回應中告訴使用者答案的依據來自哪份文件的哪個段落。
    """
    doc_id: int      # 對應 documents 資料表的 ID
    filename: str    # 原始檔名，顯示給使用者看
    chunk: str       # 實際的文字段落內容
    score: float     # 相似度分數（0~1），越高表示與問題越相關


class QueryRequest(BaseModel):
    question: str
    # doc_ids 為 None 表示在使用者所有文件中搜尋；
    # 傳入特定 ID 列表則只在那些文件中搜尋，適合「只問這份合約」的場景
    doc_ids: list[int] | None = None


class QueryResponse(BaseModel):
    answer: str              # LLM 產生的回答
    citations: list[Citation]  # 回答所依據的文件片段，讓使用者可以驗證來源


class CalcRequest(BaseModel):
    # 數學運算式字串，例如 "1 + 2 * 3" 或 "(10 / 2) ** 2"
    expression: str


class CalcResponse(BaseModel):
    expression: str       # 回傳原始運算式，方便客戶端確認計算的是哪個式子
    result: float | int   # 計算結果，整數時回傳 int，有小數時回傳 float
