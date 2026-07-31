from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Any

from auth.dependency import get_current_user_id

router = APIRouter()


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    status: str
    session_id: str
    messages: list[HistoryMessage]


@router.get("/history", response_model=HistoryResponse)
async def history_endpoint(
    session_id: str = Query(..., description="会话 ID"),
    user_id: str = Depends(get_current_user_id),
):
    """拉取指定会话的对话历史（从 Redis 短期记忆）。

    P3 安全认证体系改造：
    - user_id 不再来自 Query 参数，强制从 JWT 解析
    - 防止用户伪造 user_id 拉取他人会话历史
    - session_id 仍来自 Query（无敏感含义）

    优雅降级：
    - memory 未初始化或后端异常时返回 status="degraded"，前端以警告提示但不阻塞对话
    """
    from service.chat_service import memory

    messages: list[HistoryMessage] = []

    # memory 未初始化：系统降级，返回空列表 + degraded
    if memory is None:
        return HistoryResponse(
            status="degraded",
            session_id=session_id,
            messages=[],
        )

    try:
        recent = await memory.get_recent_messages(user_id, session_id)
        for m in recent:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append(HistoryMessage(role=role, content=content))
    except Exception as e:
        # 短期记忆后端异常（如 Redis 不可用）：降级而不是 500，避免阻塞用户开新对话
        print(f"⚠️ [history] 拉取会话历史失败，降级返回空列表: {e}")
        return HistoryResponse(
            status="degraded",
            session_id=session_id,
            messages=[],
        )

    return HistoryResponse(
        status="ok",
        session_id=session_id,
        messages=messages,
    )
