from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from schemas.chat import ChatRequest
from service.chat_service import stream_chat
from auth.dependency import get_current_user_id

router = APIRouter()

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    处理多智能体聊天请求，并使用 SSE (Server-Sent Events) 返回流式响应。

    P3 安全认证体系改造：
    - user_id 不再信任 body，强制从 JWT（Authorization header）解析
    - 未携带有效 token 一律 401
    - 即便 body 里塞了 user_id 字段也会被忽略（schema 已移除该字段）
    """
    return StreamingResponse(
        stream_chat(request.query, user_id, request.session_id),
        media_type="text/event-stream"
    )
