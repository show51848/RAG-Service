import logging

import anthropic

from app.config import settings
from app.schemas.chat import Citation

logger = logging.getLogger(__name__)

anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = (
    "你是一個知識庫助手。根據以下文件片段回答問題。\n"
    "若資訊不足，請說明無法從提供的文件中找到答案。\n"
    "請用繁體中文回答。\n"
    "回答時請引用來源，格式為 [數字]，例如 [1]、[2]。"
)


def generate_answer(question: str, citations: list[Citation]) -> tuple[str, list[Citation]]:
    """
    Build a prompt from retrieved citations and call claude-opus-4-6.
    Returns (answer_text, relevant_citations).
    """
    if not citations:
        logger.info("No citations available; returning empty-context answer")
        no_doc_answer = (
            "目前沒有找到相關文件片段，無法回答您的問題。\n"
            "請先上傳相關文件，或確認問題是否與已上傳的文件相關。"
        )
        return no_doc_answer, []

    # Build context string with numbered references
    context_lines = []
    for idx, citation in enumerate(citations, start=1):
        context_lines.append(
            f"[{idx}] 來源：{citation.filename}\n{citation.chunk}"
        )
    context = "\n\n---\n\n".join(context_lines)

    user_message = f"文件片段：\n\n{context}\n\n問題：{question}"

    logger.info("Calling claude-haiku-4-5 with %d citations", len(citations))

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message},
        ],
    )

    answer = next((block.text for block in response.content if block.type == "text"), "")
    logger.info("LLM answer length: %d chars", len(answer))

    return answer, citations
