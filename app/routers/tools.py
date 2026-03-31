import ast
import operator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.chat import CalcRequest, CalcResponse
from app.schemas.document import DocumentSummary

router = APIRouter(prefix="/tools", tags=["tools"])

# 明確列出允許的運算子白名單
# 使用白名單而非黑名單：確保只有預期的運算才能執行，防止未來 Python 新增的運算符被濫用
_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,   # 一元負號，例如 -5
    ast.UAdd: operator.pos,   # 一元正號，例如 +5
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node: ast.AST) -> float | int:
    """
    遞迴地走訪 AST（抽象語法樹），只允許數字常數和白名單運算子。

    為何不直接用 eval()：
    eval("__import__('os').system('rm -rf /')") 會直接執行系統指令，是嚴重的安全漏洞。
    用 AST 解析後只允許特定節點類型，可以安全地評估數學運算式而不執行任意程式碼。
    """
    if isinstance(node, ast.Expression):
        # Expression 是 ast.parse(mode="eval") 的根節點，直接遞迴處理 body
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        # 只允許數字常數（int/float），拒絕字串、bytes 等其他常數
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    if isinstance(node, ast.BinOp):
        # 二元運算（例如 1 + 2、3 * 4）
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _OPERATORS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        # 一元運算（例如 -5、+3）
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand)
        return _OPERATORS[op_type](operand)
    # 其他所有 AST 節點（函式呼叫、屬性存取、變數名稱等）都拒絕
    raise ValueError(f"Unsupported AST node: {type(node).__name__}")


@router.post(
    "/calc",
    response_model=CalcResponse,
    summary="Safely evaluate a mathematical expression",
)
def calc(
    body: CalcRequest,
    current_user: User = Depends(get_current_user),
) -> CalcResponse:
    """
    Evaluate a numeric math expression safely using Python's AST parser.
    **No `eval()` is used.** Supported operators: +, -, *, /, //, %, **.

    這個端點存在的原因：提供給 LLM tool calling 使用，
    讓 LLM 在需要精確計算時呼叫此端點，而非自己計算（LLM 數學運算容易出錯）。
    """
    try:
        # mode="eval" 只解析單一運算式，不允許 import、賦值、函式定義等陳述句
        tree = ast.parse(body.expression.strip(), mode="eval")
        result = _safe_eval(tree)
    except ZeroDivisionError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Division by zero",
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid expression: {exc}",
        )
    except SyntaxError:
        # ast.parse 失敗時拋出 SyntaxError（例如 "1 +" 這種不完整的運算式）
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Expression has invalid syntax",
        )
    return CalcResponse(expression=body.expression, result=result)


@router.get(
    "/docs",
    response_model=list[DocumentSummary],
    summary="Get a compact document list (for LLM tool calling)",
)
def tools_docs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentSummary]:
    """
    Return a concise summary of all indexed documents belonging to the
    authenticated user. Intended for use as a tool-calling context by LLMs.

    與 /docs 的差異：
    - 回傳 DocumentSummary（id + original_name + chunk_count）
    - 不含 status、created_at 等 LLM 不需要的欄位
    - 讓 LLM 知道有哪些文件可用，再決定要查詢哪個 doc_id
    """
    docs = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .all()
    )
    return [DocumentSummary.model_validate(d) for d in docs]
