from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

router = APIRouter()


class HealthResponse(BaseModel):
    """系统健康状态响应。"""
    status: str  # "ok" | "degraded" | "error"
    graph_ready: bool
    memory: dict[str, Any]
    cache: dict[str, Any]
    observability: dict[str, Any]


@router.get("/health", response_model=HealthResponse)
async def health_endpoint():
    """系统健康检查端点。

    返回：
    - graph_ready: Agent 图编排是否已初始化
    - memory: 短期/长期记忆后端可用性
    - cache: 语义缓存可用性
    - observability: Langfuse 可观测性启用状态

    整体状态判定：
    - error: graph 未就绪（无法服务）
    - degraded: memory/cache 等组件缺失（仍可服务，但体验受损）
    - ok: 全部关键组件可用
    """
    from service.chat_service import graph, memory
    from infra.cache import semantic_cache
    from infra.observability import get_observability_status

    graph_ready = graph is not None

    memory_status: dict[str, Any] = {"initialized": memory is not None}
    if memory is not None:
        memory_status["short_term"] = memory.short_term.available
        memory_status["long_term"] = memory.long_term.available

    cache_status: dict[str, Any] = {
        "available": semantic_cache.available,
    }

    # 整体状态：graph 不可用 = error；其他关键组件缺失 = degraded；全部正常 = ok
    if not graph_ready:
        overall = "error"
    elif (
        memory is None
        or not memory_status.get("short_term")
        or not cache_status.get("available")
    ):
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        graph_ready=graph_ready,
        memory=memory_status,
        cache=cache_status,
        observability=get_observability_status(),
    )
