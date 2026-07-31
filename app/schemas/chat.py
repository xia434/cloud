from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    """聊天请求。

    P3 安全认证体系改造：
    - user_id 不再来自 body，而是从 JWT 解析（见 chat.py 的 Depends）
    - 保留 session_id 字段（无业务约束）
    """
    query: str
    session_id: Optional[str] = "default_session"

class ChatResponse(BaseModel):
    status: str
    reply: str
    user_id: str
    session_id: str
