import logging

import anthropic

from app.config import settings
from app.schemas.chat import Citation

logger = logging.getLogger(__name__)

# 在模組層級建立 Anthropic client 單例，避免每次請求都重新初始化連線
anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# System prompt 定義 LLM 的角色與行為規範：
# 1. 限定只根據提供的文件片段回答，避免 hallucination（AI 捏造資訊）
# 2. 要求用繁體中文回答，保持語言一致性
# 3. 要求引用來源格式 [數字]，讓使用者能追溯答案依據
SYSTEM_PROMPT = (
    "你是一個知識庫助手。根據以下文件片段回答問題。\n"
    "若資訊不足，請說明無法從提供的文件中找到答案。\n"
    "請用繁體中文回答。\n"
    "回答時請引用來源，格式為 [數字]，例如 [1]、[2]。"
)


def generate_answer(question: str, citations: list[Citation]) -> tuple[str, list[Citation]]:
    """
    根據檢索到的文件片段呼叫 Claude，產生帶有引用標註的答案。

    回傳 (answer_text, citations) tuple 的原因：
    未來如果需要過濾「LLM 實際引用了哪些來源」，可以在這裡解析回答中的 [數字]
    標記並只回傳被引用的 citations，目前 MVP 階段直接回傳全部。
    """
    if not citations:
        # 沒有找到任何相關文件時，直接回傳說明訊息而不呼叫 LLM
        # 節省 API 費用，同時給使用者明確的操作指引
        logger.info("No citations available; returning empty-context answer")
        no_doc_answer = (
            "目前沒有找到相關文件片段，無法回答您的問題。\n"
            "請先上傳相關文件，或確認問題是否與已上傳的文件相關。"
        )
        return no_doc_answer, []

    # 把每個 citation 格式化成帶有編號的段落，讓 LLM 可以引用 [1]、[2] 等標記
    context_lines = []
    for idx, citation in enumerate(citations, start=1):
        context_lines.append(
            f"[{idx}] 來源：{citation.filename}\n{citation.chunk}"
        )
    # 用分隔線讓 LLM 清楚看出不同來源的邊界
    context = "\n\n---\n\n".join(context_lines)

    # 把文件片段和問題都放在 user message，而非 system prompt
    # 原因：system prompt 設定角色，user message 提供具體任務和資料
    user_message = f"文件片段：\n\n{context}\n\n問題：{question}"

    logger.info("Calling claude-haiku-4-5 with %d citations", len(citations))

    response = anthropic_client.messages.create(
        # claude-haiku-4-5：速度快、費用低，適合 RAG 場景（答案主要來自文件，不需要 Opus 的深度推理）
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,  # RAG 回答通常不需要超長輸出，限制 token 控制費用
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message},
        ],
    )

    # response.content 是 ContentBlock 列表，可能包含 text 和 tool_use 等類型
    # 用 next() 取第一個 text block，找不到時回傳空字串
    answer = next((block.text for block in response.content if block.type == "text"), "")
    logger.info("LLM answer length: %d chars", len(answer))

    return answer, citations
