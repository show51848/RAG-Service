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

# Allowed operators for safe expression evaluation
_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node: ast.AST) -> float | int:
    """Recursively evaluate a restricted AST — no eval() used."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _OPERATORS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand)
        return _OPERATORS[op_type](operand)
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

    - **expression**: e.g. `"1 + 2 * 3"`, `"(10 / 2) ** 2"`
    """
    try:
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
    """
    docs = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .all()
    )
    return [DocumentSummary.model_validate(d) for d in docs]
