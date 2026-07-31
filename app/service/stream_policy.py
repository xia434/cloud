"""Pure policy helpers for chat streaming and semantic caching."""
from __future__ import annotations

from typing import Any


FINAL_RESPONSE_NODES = {
    "product_agent",
    "billing_agent",
    "promotion_agent",
    "recommendation_agent",
    "finops_agent",
    "out_of_scope",
}

_DYNAMIC_QUERY_MARKERS = {
    "我",
    "我的",
    "我名下",
    "账单",
    "订单",
    "余额",
    "实例状态",
    "运行中",
    "最近",
    "当前",
    "实时",
    "推荐",
    "选型",
    "预算",
    "价格",
    "成本",
    "优化",
    "利用率",
    "cpu",
    "内存使用",
    "推广",
    "返佣",
    "海报",
}


def is_stable_knowledge_query(query: str) -> bool:
    """Return whether a query is safe to serve from the semantic cache.

    The cache is intentionally conservative. User-specific, time-sensitive and
    recommendation queries must always execute the Agent workflow.
    """
    normalized = " ".join(query.strip().lower().split())
    if not normalized:
        return False
    return not any(marker in normalized for marker in _DYNAMIC_QUERY_MARKERS)


def should_forward_model_event(event: dict[str, Any]) -> bool:
    """Only forward model tokens produced inside a business Agent node."""
    metadata = event.get("metadata") or {}
    node = str(metadata.get("langgraph_node", ""))
    if node == "orchestrator":
        return False
    if node in FINAL_RESPONSE_NODES:
        return True

    # ReAct agents create an inner graph whose node is usually named ``agent``.
    # checkpoint_ns retains the outer business node in that case.
    checkpoint_ns = str(metadata.get("checkpoint_ns", ""))
    # ProductAgent performs a direct, evidence-only synthesis after its inner
    # ReAct graph. Suppress the inner draft and stream only the outer synthesis.
    if "product_agent:" in checkpoint_ns:
        return False
    return any(f"{name}:" in checkpoint_ns for name in FINAL_RESPONSE_NODES)


def extract_final_response_text(output: Any) -> str:
    """Extract the final AI message from a completed business node output."""
    if not isinstance(output, dict):
        return ""
    messages = output.get("messages")
    if not messages:
        return ""
    final_message = messages[-1]
    if isinstance(final_message, tuple):
        content = final_message[1] if len(final_message) > 1 else ""
    else:
        content = getattr(final_message, "content", "")
    return content.strip() if isinstance(content, str) else ""
